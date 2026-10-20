"""TCP NewReno (RFC 6582).

Differences from Reno:

* Entering fast recovery (3 dup ACKs, only if ``ack > recover``):
  ``recover`` = highest segment sent; ssthresh = max(FlightSize/2, 2);
  retransmit; cwnd = ssthresh + 3.
* Duplicate ACK during recovery: cwnd += 1 (inflate).
* **Partial ACK** (acknowledges new data but not ``recover``): retransmit the
  first unacknowledged segment, deflate cwnd by the amount newly acknowledged
  and add back one segment (cwnd = cwnd - newly_acked + 1), and *stay* in fast
  recovery.  By default the retransmission timer is reset only for the first
  partial ACK (the "Impatient" variant, RFC 6582 section 3.2 step 5 and
  section 4); ``timer_variant="slow_but_steady"`` resets it on every partial
  ACK (the variant used in Fall & Floyd's simulations).
* **Full ACK** (acknowledges ``recover``): exit fast recovery with
  cwnd = min(ssthresh, max(FlightSize, 1) + 1)  (RFC 6582 section 3.2 step 5,
  option 1, which avoids a burst).
* Timeout: base-class behaviour; ``recover`` is set to the highest segment sent
  (RFC 6582 section 4.1).
"""

from __future__ import annotations

from algorithms.base import MIN_CWND, AckInfo, CCResponse, CongestionControl


class NewRenoCC(CongestionControl):
    name = "newreno"
    label = "TCP NewReno"

    def __init__(self, *args, timer_variant: str = "impatient", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if timer_variant not in ("impatient", "slow_but_steady"):
            raise ValueError("timer_variant must be 'impatient' or 'slow_but_steady'")
        self.timer_variant = timer_variant
        self._first_partial = True
        self.partial_acks = 0

    # Hooks overridden by CUBIC, which reuses NewReno loss recovery -------------
    def _reduce_on_loss(self, info: AckInfo) -> None:
        self.ssthresh = self._loss_ssthresh(info.loss_flight)

    def _after_full_ack(self, info: AckInfo) -> None:
        self.cwnd = min(self.ssthresh, max(float(info.flight_size), 1.0) + 1.0)

    def _grow_new_ack(self, info: AckInfo) -> None:
        self._grow(info)

    # ------------------------------------------------------------------------
    def on_new_ack(self, info: AckInfo) -> CCResponse:
        if not self.in_recovery:
            self._grow_new_ack(info)
            return CCResponse()

        if info.ack > self.recover:  # full acknowledgement
            self.in_recovery = False
            self._after_full_ack(info)
            self._clamp()
            return CCResponse(events=[("exit_recovery", f"full ACK {info.ack} covers recover={self.recover}; "
                                                        f"cwnd={self.cwnd:.2f}")])

        # partial acknowledgement: another segment from the same window was lost
        self.cwnd = max(self.cwnd - info.newly_acked + (1.0 if info.newly_acked >= 1 else 0.0), MIN_CWND)
        restart = self._first_partial or self.timer_variant == "slow_but_steady"
        self._first_partial = False
        self.partial_acks += 1
        return CCResponse(
            retransmit_head=True,
            restart_timer=restart,
            send_kind="partial_retx",
            events=[("partial_ack", f"ack={info.ack} < recover+1={self.recover + 1}; retransmit seg {info.ack}, "
                                    f"stay in fast recovery (cwnd={self.cwnd:.2f})")],
        )

    def on_dupack(self, info: AckInfo, dupacks: int) -> CCResponse:
        if self.in_recovery:
            self.cwnd += 1.0
            return CCResponse()
        if dupacks == 3 and self._can_fast_retransmit(info.ack):
            self.recover = info.snd_max - 1
            self._reduce_on_loss(info)
            self.cwnd = self.ssthresh + 3.0
            self.in_recovery = True
            self._first_partial = True
            return CCResponse(
                retransmit_head=True,
                send_kind="fast_retx",
                events=[("fast_retransmit", f"3 dup ACKs for seg {info.ack}"),
                        ("enter_recovery", f"recover={self.recover}, ssthresh={self.ssthresh:.2f}, "
                                           f"cwnd={self.cwnd:.2f}")],
            )
        return CCResponse()

    def state(self):
        s = super().state()
        s["partial_acks"] = self.partial_acks
        return s
