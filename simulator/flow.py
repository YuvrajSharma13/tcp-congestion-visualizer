"""TCP sender: sequence bookkeeping, duplicate-ACK counting, retransmission timer.

The sender is algorithm-agnostic.  It calls the congestion control object on
new ACKs, duplicate ACKs and timeouts, and acts on the returned ``CCResponse``.

Sequence variables (all in segments):
  ``snd_una`` oldest unacknowledged segment
  ``snd_nxt`` next segment to transmit (reset to snd_una by a go-back-N response)
  ``snd_max`` one past the highest segment ever transmitted

A transmission is a *retransmission* iff its segment number is < ``snd_max``.
Sending is allowed while ``snd_nxt - snd_una < min(floor(cwnd), rwnd)``.

Retransmission timer (RFC 6298 section 5):
  5.1 start the timer when a segment is sent and the timer is not running;
  5.2 stop it when all outstanding data is acknowledged;
  5.3 restart it when an ACK acknowledges new data (NewReno/CUBIC may ask not
      to restart it on later partial ACKs, RFC 6582 "Impatient" variant);
  5.4-5.6 on expiry: retransmit, double the RTO, restart the timer.
The timer is *lazily* rescheduled: at most one pending heap entry exists per
flow (``timer_event_time``).  When that entry fires before the current deadline
(because the timer was restarted) it is simply re-armed for the deadline; when
the timer has been stopped it is ignored.  A timeout therefore can never fire
for data that has already been acknowledged.

``sacked_est`` counts segments that duplicate ACKs show have reached the
receiver beyond a hole (Linux-style duplicate-ACK "SACK emulation" for
non-SACK flows).  It is only used to compute ``AckInfo.loss_flight``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from algorithms import create_algorithm
from algorithms.base import AckInfo, CCResponse
from config.validation import FlowConfig, SimulationConfig
from simulator.packets import AckPacket
from simulator.rto import RtoEstimator
from simulator import trace as T

if TYPE_CHECKING:  # pragma: no cover
    from simulator.engine import Simulator


class TcpSender:
    def __init__(self, flow_id: int, fcfg: FlowConfig, cfg: SimulationConfig, sim: "Simulator") -> None:
        self.flow_id = flow_id
        self.sim = sim
        self.algorithm_name = fcfg.algorithm
        self.cc = create_algorithm(fcfg.algorithm, fcfg.initial_cwnd, fcfg.initial_ssthresh,
                                   cubic_c=cfg.cubic_c, cubic_beta=cfg.cubic_beta,
                                   cubic_fast_convergence=cfg.cubic_fast_convergence,
                                   newreno_timer_variant=cfg.newreno_timer_variant)
        self.rto = RtoEstimator(cfg.initial_rto_s, cfg.min_rto_s, cfg.max_rto_s, cfg.clock_granularity_s)
        self.rwnd = cfg.receiver_window
        self.start_time = fcfg.start_time_s

        self.snd_una = 0
        self.snd_nxt = 0
        self.snd_max = 0
        self.dupacks = 0
        self.started = False
        self.min_rtt: float | None = None

        self.timer_running = False
        self.timer_deadline = math.inf
        self.timer_event_time = math.inf
        self.sacked_est = 0
        self._pending_kind = ""

        # counters
        self.sent_packets = 0
        self.new_packets = 0
        self.retx_packets = 0
        self.fast_retransmits = 0
        self.timeouts = 0
        self.partial_acks = 0
        self.recovery_episodes = 0
        self.dupacks_total = 0
        self.acks_received = 0
        self.rtt_count = 0
        self.rtt_sum_ms = 0.0
        self.rtt_sq_sum_ms = 0.0
        self.drops = 0
        self.overflow_drops = 0
        self.drops_by_type = {k: 0 for k in T.DROP_TYPES}

        self._last_state: tuple[float, float, str] | None = None

    # ------------------------------------------------------------------ helpers
    @property
    def window(self) -> int:
        return min(int(math.floor(self.cc.cwnd + 1e-9)), self.rwnd)

    @property
    def flight(self) -> int:
        return self.snd_max - self.snd_una

    def _info(self, now: float, ack: int, newly: int) -> AckInfo:
        flight = self.snd_max - self.snd_una
        earlier_sacked = max(self.sacked_est - self.dupacks, 0)
        return AckInfo(now=now, ack=ack, newly_acked=newly, flight_size=flight,
                       loss_flight=max(flight - earlier_sacked, 1),
                       snd_max=self.snd_max, srtt=self.rto.srtt, min_rtt=self.min_rtt)

    def record_state(self, now: float, force: bool = False) -> None:
        state = (self.cc.cwnd, self.cc.ssthresh, self.cc.phase)
        last = self._last_state
        if force or last is None or state != last:
            self.sim.trace.cwnd.append((now, self.flow_id, state[0], state[1], state[2]))
            if last is not None and last[2] != state[2]:
                self.sim.log(now, T.EV_PHASE_CHANGE, self.flow_id, seq=self.snd_una,
                             info=f"{last[2]}->{state[2]}")
            self._last_state = state

    # ----------------------------------------------------------------- sending
    def start(self, now: float) -> None:
        self.started = True
        self.sim.log(now, T.EV_FLOW_START, self.flow_id, info=self.algorithm_name)
        self.record_state(now, force=True)
        self.try_send(now)

    def try_send(self, now: float) -> None:
        wnd = self.window
        while self.snd_nxt - self.snd_una < wnd:
            kind = ""
            if self.snd_nxt < self.snd_max and self._pending_kind:
                kind = self._pending_kind
                self._pending_kind = ""
            self._transmit(self.snd_nxt, now, kind)
            self.snd_nxt += 1

    def _transmit(self, seq: int, now: float, kind: str) -> None:
        is_retx = seq < self.snd_max
        if not is_retx:
            kind = "new"
            self.new_packets += 1
        else:
            kind = kind or "gbn_retx"
            self.retx_packets += 1
        self.sent_packets += 1
        if seq >= self.snd_max:
            self.snd_max = seq + 1
        self.sim.send_data(self.flow_id, seq, now, is_retx, kind)
        if not self.timer_running:
            self._start_timer(now)

    # ------------------------------------------------------------------- timer
    def _start_timer(self, now: float) -> None:
        self.timer_running = True
        self.timer_deadline = now + self.rto.rto
        if self.timer_deadline < self.timer_event_time:
            self.timer_event_time = self.timer_deadline
            self.sim.schedule_rto(self.timer_deadline, self.flow_id, self.timer_deadline)

    def _stop_timer(self) -> None:
        self.timer_running = False
        self.timer_deadline = math.inf

    # -------------------------------------------------------------------- ACKs
    def on_ack(self, ack: AckPacket, now: float) -> None:
        self.acks_received += 1
        sample: float | None = None
        if not ack.echo_is_retx:  # Karn's algorithm
            sample = now - ack.echo_sent_at
            ms = sample * 1000.0
            self.rtt_count += 1
            self.rtt_sum_ms += ms
            self.rtt_sq_sum_ms += ms * ms
            self.sim.trace.rtt.append((now, self.flow_id, sample))
            if self.min_rtt is None or sample < self.min_rtt:
                self.min_rtt = sample

        a = ack.ack
        if a > self.snd_una:
            newly = a - self.snd_una
            if sample is not None:
                self.rto.update(sample)
            self.snd_una = a
            if self.snd_nxt < self.snd_una:
                self.snd_nxt = self.snd_una
            self.dupacks = 0
            if self.sacked_est:
                self.sacked_est = max(self.sacked_est - (newly - 1), 0)
            self.sacked_est = min(self.sacked_est, max(self.snd_max - self.snd_una - 1, 0))
            self.sim.log_packet(now, T.EV_ACK_RX, self.flow_id, seq=a, info="new")
            resp = self.cc.on_new_ack(self._info(now, a, newly))
            self._apply(resp, now, new_ack=True)
        elif a == self.snd_una and self.snd_una < self.snd_max:
            self.dupacks += 1
            self.dupacks_total += 1
            self.sacked_est = min(self.sacked_est + 1, max(self.snd_max - self.snd_una - 1, 0))
            self.sim.log_packet(now, T.EV_ACK_RX, self.flow_id, seq=a, info=f"dup#{self.dupacks}")
            resp = self.cc.on_dupack(self._info(now, a, 0), self.dupacks)
            self._apply(resp, now, new_ack=False)
        else:
            self.sim.log_packet(now, T.EV_ACK_RX, self.flow_id, seq=a, info="old")
        self.try_send(now)
        self.record_state(now)

    def _apply(self, resp: CCResponse, now: float, new_ack: bool) -> None:
        for ev, detail in resp.events:
            if ev == T.EV_FAST_RETRANSMIT:
                self.fast_retransmits += 1
            elif ev == T.EV_PARTIAL_ACK:
                self.partial_acks += 1
            elif ev == T.EV_ENTER_RECOVERY:
                self.recovery_episodes += 1
            self.sim.log(now, ev, self.flow_id, seq=self.snd_una, info=detail)
        if new_ack:
            if self.snd_una >= self.snd_max:
                self._stop_timer()
            elif resp.restart_timer:
                self._start_timer(now)
        if resp.go_back_n:
            self.snd_nxt = self.snd_una
            self._pending_kind = resp.send_kind
        if resp.retransmit_head:
            self._transmit(self.snd_una, now, resp.send_kind)
            if self.snd_nxt == self.snd_una:
                self.snd_nxt += 1

    # ----------------------------------------------------------------- timeout
    def on_rto(self, scheduled_for: float, now: float) -> bool:
        """Handle a timer heap entry.  Returns False if it did not cause a timeout."""
        if scheduled_for != self.timer_event_time:
            return False  # an older entry superseded by an earlier deadline
        self.timer_event_time = math.inf
        if not self.timer_running:
            return False  # timer was stopped: all data acknowledged
        if now < self.timer_deadline:  # timer was restarted: re-arm for the new deadline
            self.timer_event_time = self.timer_deadline
            self.sim.schedule_rto(self.timer_deadline, self.flow_id, self.timer_deadline)
            return False
        self.timer_running = False
        self.timer_deadline = math.inf
        if self.snd_una >= self.snd_max:
            return False
        self.timeouts += 1
        self.sim.log(now, T.EV_TIMEOUT, self.flow_id, seq=self.snd_una,
                     info=f"RTO={self.rto.rto * 1000:.0f} ms expired; seg {self.snd_una} unacknowledged, "
                          f"flight={self.flight}")
        resp = self.cc.on_timeout(self._info(now, self.snd_una, 0))
        self.rto.backoff()
        self.dupacks = 0
        self.sacked_est = 0
        self._apply(resp, now, new_ack=False)
        self.try_send(now)
        if not self.timer_running:
            self._start_timer(now)
        self.record_state(now)
        return True

    # ------------------------------------------------------------------- stats
    def stats(self) -> dict:
        return {
            "flow": self.flow_id,
            "algorithm": self.algorithm_name,
            "start_time_s": self.start_time,
            "sent_packets": self.sent_packets,
            "new_packets": self.new_packets,
            "retx_packets": self.retx_packets,
            "fast_retransmits": self.fast_retransmits,
            "timeouts": self.timeouts,
            "partial_acks": self.partial_acks,
            "recovery_episodes": self.recovery_episodes,
            "dupacks": self.dupacks_total,
            "acks_received": self.acks_received,
            "drops": self.drops,
            **{f"drops_{k}": v for k, v in self.drops_by_type.items()},
            "snd_una": self.snd_una,
            "snd_max": self.snd_max,
            "final_cwnd": self.cc.cwnd,
            "final_ssthresh": self.cc.ssthresh,
            "final_rto_s": self.rto.rto,
            "srtt_s": self.rto.srtt,
        }
