"""TCP Reno (RFC 5681 section 3.2: fast retransmit / fast recovery).

On the third duplicate ACK (and ``ack > recover``):
  1. ssthresh = max(FlightSize/2, 2)
  2. retransmit the lost segment
  3. cwnd = ssthresh + 3  (the three segments that left the network)
For each further duplicate ACK while in fast recovery: cwnd += 1 (inflation),
which lets new segments be sent.
On the next ACK that acknowledges new data: cwnd = ssthresh (deflation) and
fast recovery ends - even if that ACK is only *partial*.  This is the classic
Reno weakness with several losses per window: it may halve cwnd again or wait
for an RTO.

``recover`` is updated only on a timeout (RFC 6582 section 4.1 behaviour), so
false fast retransmits after a go-back-N RTO recovery are avoided while the
classic Reno multiple-loss behaviour is preserved.
"""

from __future__ import annotations

from algorithms.base import AckInfo, CCResponse, CongestionControl


class RenoCC(CongestionControl):
    name = "reno"
    label = "TCP Reno"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._recovery_point = -1

    def on_new_ack(self, info: AckInfo) -> CCResponse:
        if self.in_recovery:
            self.cwnd = self.ssthresh
            self.in_recovery = False
            full = info.ack > self._recovery_point
            detail = "full ACK" if full else f"partial ACK (ack={info.ack}); Reno exits anyway"
            return CCResponse(events=[("exit_recovery", f"cwnd deflated to ssthresh={self.ssthresh:.2f}; {detail}")])
        self._grow(info)
        return CCResponse()

    def on_dupack(self, info: AckInfo, dupacks: int) -> CCResponse:
        if self.in_recovery:
            self.cwnd += 1.0
            return CCResponse()
        if dupacks == 3 and self._can_fast_retransmit(info.ack):
            self.ssthresh = self._loss_ssthresh(info.loss_flight)
            self.cwnd = self.ssthresh + 3.0
            self.in_recovery = True
            self._recovery_point = info.snd_max - 1  # only used to label the exit as full/partial
            return CCResponse(
                retransmit_head=True,
                send_kind="fast_retx",
                events=[("fast_retransmit", f"3 dup ACKs for seg {info.ack}"),
                        ("enter_recovery", f"ssthresh={self.ssthresh:.2f}, cwnd=ssthresh+3={self.cwnd:.2f}")],
            )
        return CCResponse()
