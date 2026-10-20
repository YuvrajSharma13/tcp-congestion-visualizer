"""Retransmission timeout estimation following RFC 6298.

* First measurement R:      SRTT = R, RTTVAR = R/2
* Subsequent measurements:  RTTVAR = (1-beta)*RTTVAR + beta*|SRTT - R'|
                            SRTT   = (1-alpha)*SRTT + alpha*R'
* RTO = SRTT + max(G, K*RTTVAR), then clamped to [min_rto, max_rto]
* On expiry the RTO is doubled ("back off the timer", section 5.5), capped at max_rto.
* Karn's algorithm: callers must not feed samples from retransmitted segments.
  A backed-off RTO is kept until a new valid sample arrives, at which point the
  RTO is recomputed from SRTT/RTTVAR (section 5.7 / Karn).
"""

from __future__ import annotations

from config import defaults as D


class RtoEstimator:
    __slots__ = ("srtt", "rttvar", "rto", "min_rto", "max_rto", "granularity", "backoffs", "samples")

    def __init__(
        self,
        initial_rto: float = D.DEFAULT_INITIAL_RTO_S,
        min_rto: float = D.DEFAULT_MIN_RTO_S,
        max_rto: float = D.DEFAULT_MAX_RTO_S,
        granularity: float = D.DEFAULT_CLOCK_GRANULARITY_S,
    ) -> None:
        self.srtt: float | None = None
        self.rttvar: float | None = None
        self.min_rto = min_rto
        self.max_rto = max_rto
        self.granularity = granularity
        self.rto = min(max(initial_rto, min_rto), max_rto)
        self.backoffs = 0
        self.samples = 0

    def update(self, r: float) -> None:
        if r < 0:
            raise ValueError("RTT sample must be non-negative")
        if self.srtt is None:
            self.srtt = r
            self.rttvar = r / 2.0
        else:
            assert self.rttvar is not None
            self.rttvar = (1.0 - D.RTO_BETA) * self.rttvar + D.RTO_BETA * abs(self.srtt - r)
            self.srtt = (1.0 - D.RTO_ALPHA) * self.srtt + D.RTO_ALPHA * r
        self.rto = self._clamp(self.srtt + max(self.granularity, D.RTO_K * self.rttvar))
        self.backoffs = 0
        self.samples += 1

    def backoff(self) -> None:
        self.rto = min(self.rto * 2.0, self.max_rto)
        self.backoffs += 1

    def _clamp(self, value: float) -> float:
        return min(max(value, self.min_rto), self.max_rto)
