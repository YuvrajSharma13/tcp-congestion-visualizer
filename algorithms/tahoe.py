"""TCP Tahoe (Jacobson 1988; RFC 5681 slow start, congestion avoidance, fast retransmit).

* Slow start / congestion avoidance as in RFC 5681.
* On the third duplicate ACK: fast retransmit, ssthresh = max(FlightSize/2, 2),
  cwnd = 1 segment, and slow start begins again.  Tahoe has **no fast recovery**.
* Like the ns-2 Tahoe agent studied by Fall & Floyd (1996), the sender
  "goes back N": it resumes sending from the lost segment, which may resend
  segments the receiver already holds.  ``recover`` stops the duplicate ACKs
  produced by those redundant segments from triggering another fast retransmit.
* On RTO: same reduction (base class).
"""

from __future__ import annotations

from algorithms.base import MIN_CWND, AckInfo, CCResponse, CongestionControl


class TahoeCC(CongestionControl):
    name = "tahoe"
    label = "TCP Tahoe"

    def on_new_ack(self, info: AckInfo) -> CCResponse:
        self._grow(info)
        return CCResponse()

    def on_dupack(self, info: AckInfo, dupacks: int) -> CCResponse:
        if dupacks == 3 and self._can_fast_retransmit(info.ack):
            self.ssthresh = self._loss_ssthresh(info.loss_flight)
            self.cwnd = MIN_CWND
            self.recover = info.snd_max - 1
            return CCResponse(
                go_back_n=True,
                send_kind="fast_retx",
                events=[("fast_retransmit", f"3 dup ACKs for seg {info.ack}"),
                        ("cwnd_reset", f"Tahoe: ssthresh={self.ssthresh:.2f}, cwnd=1, slow start")],
            )
        return CCResponse()
