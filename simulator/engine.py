"""Discrete-event simulation engine.

Topology (dumbbell with a single bottleneck)::

    sender 0 ─┐                                         ┌─> receiver 0
    sender 1 ─┼─> [ FIFO drop-tail buffer ] ══ link ══> ┼─> receiver 1
    cross    ─┘        (buffer_packets)   bandwidth,    └─> (cross-traffic sink)
                                          delay
    receivers ── ACKs (propagation delay only, never lost) ──> senders

* Access links are infinitely fast: a packet released by a sender reaches the
  bottleneck at the same simulated instant.
* Random / burst / forced losses apply to TCP **data packets only**, at the end
  of their serialization on the bottleneck (the packet used link capacity, then
  was lost on the wire).  ACKs are never lost.  Overflow drops happen when a
  packet arrives at a full buffer.  Every loss is written to the event log with
  its cause.
* Randomness: ``numpy.random.SeedSequence(seed)`` is split into one independent
  stream per flow (link loss decisions) plus one for cross traffic, so a fixed
  seed reproduces a run exactly.

Usage::

    from simulator.engine import run_simulation
    result = run_simulation(config)
"""

from __future__ import annotations

import time as _time

import numpy as np

from config import defaults as D
from config.validation import SimulationConfig
from simulator import trace as T
from simulator.events import EventQueue, EventType
from simulator.flow import TcpSender
from simulator.network import BottleneckLink, Receiver
from simulator.packets import CROSS_FLOW_ID, AckPacket, DataPacket

_PHASE_CODE = {"slow_start": 0, "congestion_avoidance": 1, "fast_recovery": 2}


class _UniformStream:
    """Buffered uniform(0,1) draws from a numpy Generator (deterministic)."""

    __slots__ = ("_rng", "_buf", "_i")

    def __init__(self, rng: np.random.Generator, block: int = 4096) -> None:
        self._rng = rng
        self._buf = rng.random(block)
        self._i = 0

    def next(self) -> float:
        if self._i >= len(self._buf):
            self._buf = self._rng.random(len(self._buf))
            self._i = 0
        v = self._buf[self._i]
        self._i += 1
        return float(v)


class Simulator:
    def __init__(self, config: SimulationConfig) -> None:
        self.cfg = config.ensure_valid()
        self.now = 0.0
        self.queue = EventQueue()
        self.link = BottleneckLink(config.bandwidth_bps, config.one_way_delay_s, config.buffer_packets)
        self.trace = T.TraceRecorder(record_packet_events=config.record_packet_events)
        n = config.n_flows
        children = np.random.SeedSequence(config.seed).spawn(n + 1)
        self.loss_streams = [_UniformStream(np.random.default_rng(c)) for c in children[:n]]
        self.cross_rng = np.random.default_rng(children[n])
        self.receivers = [Receiver(i) for i in range(n)]
        self.senders = [TcpSender(i, f, config, self) for i, f in enumerate(config.flows)]
        self._uid = 0
        self._forced = {(fd.flow_id, fd.seq) for fd in config.forced_drops}
        self._bursts = sorted((b.start_s, b.start_s + b.duration_s) for b in config.loss_bursts)
        self.link_bytes_total = 0
        self.overflow_drops_total = 0
        self.cross_sent = 0
        self.cross_dropped = 0
        self.cross_delivered = 0
        self.stale_timers = 0
        self.events_processed = 0

    # ------------------------------------------------------------- logging API
    def log(self, t: float, event: str, flow: int, seq: int = -1, uid: int = -1, info: str = "") -> None:
        if 0 <= flow < len(self.senders):
            cc = self.senders[flow].cc
            self.trace.event(t, event, flow, seq, uid, info, cc.cwnd, cc.ssthresh, self.link.occupancy)
        else:
            self.trace.event(t, event, flow, seq, uid, info, queue=self.link.occupancy)

    def log_packet(self, t: float, event: str, flow: int, seq: int = -1, uid: int = -1, info: str = "") -> None:
        if self.trace.record_packet_events:
            self.log(t, event, flow, seq, uid, info)

    def _queue_changed(self) -> None:
        self.trace.queue.append((self.now, self.link.occupancy))

    # -------------------------------------------------------------- scheduling
    def schedule_rto(self, at: float, flow: int, token: float) -> None:
        self.queue.push(at, EventType.RTO_EXPIRE, (flow, token))

    # ------------------------------------------------------------- data path
    def send_data(self, flow: int, seq: int, now: float, is_retx: bool, kind: str) -> None:
        self._uid += 1
        pkt = DataPacket(self._uid, flow, seq, self.cfg.mss_bytes, now, is_retx, kind)
        if is_retx:
            self.log(now, T.EV_SEND, flow, seq, pkt.uid, kind)
        else:
            self.log_packet(now, T.EV_SEND, flow, seq, pkt.uid, kind)
        self._offer(pkt)

    def _offer(self, pkt: DataPacket) -> None:
        now = self.now
        result = self.link.offer(pkt, now)
        if result == "dropped":
            self._drop(pkt, T.DROP_OVERFLOW)
            return
        self.log_packet(now, T.EV_ENQUEUE, pkt.flow_id, pkt.seq, pkt.uid, result)
        if result == "tx":
            self.log_packet(now, T.EV_TX_START, pkt.flow_id, pkt.seq, pkt.uid)
            self.queue.push(now + self.link.tx_time(pkt), EventType.LINK_TX_COMPLETE)
        else:
            self._queue_changed()

    def _drop(self, pkt: DataPacket, cause: str) -> None:
        if pkt.flow_id == CROSS_FLOW_ID:
            self.cross_dropped += 1
        else:
            s = self.senders[pkt.flow_id]
            s.drops += 1
            s.drops_by_type[cause] += 1
            if cause == T.DROP_OVERFLOW:
                s.overflow_drops += 1
        if cause == T.DROP_OVERFLOW:
            self.overflow_drops_total += 1
        info = cause
        if cause == T.DROP_OVERFLOW:
            info = f"{cause}: buffer full ({self.link.occupancy}/{self.link.capacity})"
        self.log(self.now, T.EV_DROP, pkt.flow_id, pkt.seq, pkt.uid, info)

    def _loss_cause(self, pkt: DataPacket) -> str | None:
        key = (pkt.flow_id, pkt.seq)
        if key in self._forced and not pkt.is_retx:
            self._forced.discard(key)
            return T.DROP_FORCED
        now = self.now
        for start, end in self._bursts:
            if start <= now < end:
                return T.DROP_BURST
            if start > now:
                break
        p = self.cfg.loss_prob
        if p > 0.0 and self.loss_streams[pkt.flow_id].next() < p:
            return T.DROP_RANDOM
        return None

    # ------------------------------------------------------------ event handlers
    def _on_tx_complete(self) -> None:
        now = self.now
        done, nxt = self.link.complete(now)
        self.link_bytes_total += done.size_bytes
        self.trace.link.append((now, done.flow_id, done.size_bytes, done.is_retx))
        self.log_packet(now, T.EV_TX_END, done.flow_id, done.seq, done.uid)
        if nxt is not None:
            self._queue_changed()
            self.log_packet(now, T.EV_TX_START, nxt.flow_id, nxt.seq, nxt.uid)
            self.queue.push(now + self.link.tx_time(nxt), EventType.LINK_TX_COMPLETE)
        if done.flow_id == CROSS_FLOW_ID:
            self.cross_delivered += 1  # cross traffic is absorbed by its sink
            return
        cause = self._loss_cause(done)
        if cause is not None:
            self._drop(done, cause)
            return
        self.queue.push(now + self.link.delay_s, EventType.DATA_ARRIVAL, done)

    def _on_data_arrival(self, pkt: DataPacket) -> None:
        now = self.now
        rcv = self.receivers[pkt.flow_id]
        cls, advanced = rcv.receive(pkt.seq)
        if advanced:
            self.trace.deliveries.append((now, pkt.flow_id, advanced))
        ack = AckPacket(pkt.flow_id, rcv.rcv_nxt, pkt.seq, pkt.uid, pkt.sent_at, pkt.is_retx, now)
        self.log_packet(now, T.EV_RX, pkt.flow_id, pkt.seq, pkt.uid, f"{cls}; ACK {rcv.rcv_nxt}")
        self.queue.push(now + self.link.delay_s, EventType.ACK_ARRIVAL, ack)

    def _on_cross_arrival(self) -> None:
        ct = self.cfg.cross_traffic
        now = self.now
        self._uid += 1
        self.cross_sent += 1
        pkt = DataPacket(self._uid, CROSS_FLOW_ID, -1, self.cfg.mss_bytes, now, False, "cross")
        self._offer(pkt)
        mean_gap = self.cfg.mss_bytes * 8.0 / (ct.rate_mbps * 1e6)
        gap = mean_gap if ct.pattern == "cbr" else float(self.cross_rng.exponential(mean_gap))
        nxt = now + gap
        stop = ct.stop_time_s if ct.stop_time_s is not None else self.cfg.duration_s
        if nxt < stop:
            self.queue.push(nxt, EventType.CROSS_ARRIVAL)

    def _on_sample(self) -> None:
        now = self.now
        q = self.link.occupancy
        for s in self.senders:
            if not s.started:
                continue
            cc = s.cc
            self.trace.samples.append((
                now, s.flow_id, cc.cwnd, cc.ssthresh, _PHASE_CODE[cc.phase], q, s.snd_una, s.snd_max,
                self.receivers[s.flow_id].delivered_segments, s.sent_packets, s.retx_packets, s.drops,
                s.overflow_drops, s.dupacks_total, s.timeouts, s.fast_retransmits,
                (s.rto.srtt * 1000.0) if s.rto.srtt is not None else float("nan"),
                s.rtt_count, s.rtt_sum_ms, s.rtt_sq_sum_ms, self.link_bytes_total, self.overflow_drops_total,
            ))
        nxt = now + self.cfg.sample_interval_s
        if nxt <= self.cfg.duration_s + 1e-12:
            self.queue.push(nxt, EventType.SAMPLE)

    # ---------------------------------------------------------------------- run
    def run(self) -> T.SimulationResult:
        cfg = self.cfg
        wall0 = _time.perf_counter()
        for i, f in enumerate(cfg.flows):
            self.queue.push(f.start_time_s, EventType.FLOW_START, i)
        self.queue.push(0.0, EventType.SAMPLE)
        if cfg.cross_traffic.enabled:
            self.queue.push(cfg.cross_traffic.start_time_s, EventType.CROSS_ARRIVAL)

        termination = "no_events"
        q = self.queue
        while q:
            t = q.peek_time()
            if t is not None and t > cfg.duration_s:
                termination = "duration_reached"
                break
            if self.events_processed >= cfg.max_events:
                termination = "event_limit"
                break
            t, etype, payload = q.pop()
            if t < self.now:
                raise RuntimeError(f"Event time went backwards: {t} < {self.now}")
            self.now = t
            self.events_processed += 1
            if etype is EventType.LINK_TX_COMPLETE:
                self._on_tx_complete()
            elif etype is EventType.DATA_ARRIVAL:
                self._on_data_arrival(payload)
            elif etype is EventType.ACK_ARRIVAL:
                self.senders[payload.flow_id].on_ack(payload, t)
            elif etype is EventType.RTO_EXPIRE:
                flow, token = payload
                if not self.senders[flow].on_rto(token, t):
                    self.stale_timers += 1
            elif etype is EventType.CROSS_ARRIVAL:
                self._on_cross_arrival()
            elif etype is EventType.FLOW_START:
                self.senders[payload].start(t)
            elif etype is EventType.SAMPLE:
                self._on_sample()

        flow_stats = []
        for s in self.senders:
            st = s.stats()
            st["delivered_segments"] = self.receivers[s.flow_id].delivered_segments
            st["receiver_duplicates"] = self.receivers[s.flow_id].duplicates
            flow_stats.append(st)
        run_info = {
            "simulator_version": D.SIMULATOR_VERSION,
            "events_processed": self.events_processed,
            "termination": termination,
            "end_time_s": min(self.now, cfg.duration_s) if termination != "duration_reached" else cfg.duration_s,
            "wall_time_s": _time.perf_counter() - wall0,
            "timer_events_without_timeout": self.stale_timers,
            "link_bytes_total": self.link_bytes_total,
            "overflow_drops_total": self.overflow_drops_total,
            "max_queue_seen": self.link.max_occupancy_seen,
            "cross_sent": self.cross_sent,
            "cross_dropped": self.cross_dropped,
            "cross_delivered": self.cross_delivered,
        }
        return T.build_result(cfg, self.trace, flow_stats, run_info)


def run_simulation(config: SimulationConfig) -> T.SimulationResult:
    """Validate ``config``, run it and return the full trace."""
    return Simulator(config).run()
