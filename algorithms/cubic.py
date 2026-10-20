"""TCP CUBIC (RFC 9438), window in segments, time in seconds.

Window growth during congestion avoidance (RFC 9438 sections 4.2-4.5)::

    W_cubic(t) = C * (t - K)^3 + W_max
    K          = cbrt((W_max - cwnd_epoch) / C)
    target     = clamp(W_cubic(t + RTT), cwnd, 1.5 * cwnd)
    cwnd      += (target - cwnd) / cwnd            per ACK of new data

``t`` is the time since the current congestion-avoidance stage began
(``epoch_start``) and ``cwnd_epoch`` is cwnd at that moment.  With
cwnd_epoch = beta * W_max this reduces to the formula in the project report,
K = cbrt(W_max * (1 - beta) / C).

Reno-friendly region (section 4.3)::

    alpha_cubic = 3 * (1 - beta) / (1 + beta)   (1.0 once W_est >= cwnd_prior)
    W_est      += alpha_cubic * segments_acked / cwnd
    if W_cubic(t) < W_est: cwnd = W_est

Multiplicative decrease (section 4.6) and fast convergence (section 4.7), on
three duplicate ACKs::

    cwnd_prior = cwnd
    W_max      = cwnd * (1 + beta) / 2   if fast convergence and cwnd < previous W_max
                 cwnd                    otherwise
    ssthresh   = max(FlightSize * beta, 2)

Loss *recovery* reuses NewReno (RFC 6582) fast recovery with partial-ACK
handling, entered with cwnd = ssthresh + 3.  This is a documented
simplification: RFC 9438 leaves the recovery mechanism to RFC 5681/6582/6675,
and Linux uses SACK-based recovery with PRR instead.

Timeout (section 4.8): ssthresh = max(FlightSize * beta, 2), cwnd = 1; in the
first congestion-avoidance stage afterwards K = 0 and W_max = cwnd_epoch.

Defaults: C = 0.4, beta = 0.7.  HyStart++ is not modelled (standard slow start).
"""

from __future__ import annotations

import math

from algorithms.base import MIN_CWND, MIN_SSTHRESH, AckInfo, CCResponse
from algorithms.newreno import NewRenoCC
from config import defaults as D


class CubicCC(NewRenoCC):
    name = "cubic"
    label = "TCP CUBIC"

    def __init__(self, initial_cwnd: float = D.DEFAULT_INITIAL_CWND,
                 initial_ssthresh: float = D.DEFAULT_INITIAL_SSTHRESH,
                 c: float = D.CUBIC_C, beta: float = D.CUBIC_BETA, fast_convergence: bool = True,
                 timer_variant: str = "impatient") -> None:
        super().__init__(initial_cwnd, initial_ssthresh, timer_variant=timer_variant)
        self.c = c
        self.beta = beta
        self.fast_convergence = fast_convergence
        self.alpha_aimd = 3.0 * (1.0 - beta) / (1.0 + beta)
        self.w_max: float | None = None
        self.k: float = 0.0
        self.epoch_start: float | None = None
        self.cwnd_epoch: float = 0.0
        self.w_est: float = 0.0
        self.cwnd_prior: float | None = None
        self.after_timeout = False
        self.region = ""  # "concave", "convex" or "reno_friendly" (last CA update)

    # ------------------------------------------------------------- the function
    def w_cubic(self, t: float) -> float:
        assert self.w_max is not None
        return self.c * (t - self.k) ** 3 + self.w_max

    @staticmethod
    def compute_k(w_max: float, cwnd_epoch: float, c: float) -> float:
        return math.copysign(abs((w_max - cwnd_epoch) / c) ** (1.0 / 3.0), w_max - cwnd_epoch)

    # ------------------------------------------------------------ NewReno hooks
    def _reduce_on_loss(self, info: AckInfo) -> None:
        self.cwnd_prior = self.cwnd
        if self.fast_convergence and self.w_max is not None and self.cwnd < self.w_max:
            self.w_max = self.cwnd * (1.0 + self.beta) / 2.0
        else:
            self.w_max = self.cwnd
        self.ssthresh = max(info.loss_flight * self.beta, MIN_SSTHRESH)
        self.epoch_start = None
        self.after_timeout = False

    def _grow_new_ack(self, info: AckInfo) -> None:
        if self.cwnd < self.ssthresh:  # slow start
            self.cwnd += 1.0
            return
        if self.epoch_start is None:
            self._begin_epoch(info.now)
        t = info.now - self.epoch_start  # type: ignore[operator]
        rtt = info.srtt if info.srtt is not None else (info.min_rtt or 0.0)
        target = min(max(self.w_cubic(t + rtt), self.cwnd), 1.5 * self.cwnd)

        alpha = 1.0 if (self.cwnd_prior is not None and self.w_est >= self.cwnd_prior) else self.alpha_aimd
        self.w_est += alpha * max(info.newly_acked, 1) / self.cwnd

        if self.w_cubic(t) < self.w_est:
            self.cwnd = max(self.cwnd, self.w_est)
            self.region = "reno_friendly"
        else:
            self.region = "concave" if self.cwnd < self.w_max else "convex"  # type: ignore[operator]
            self.cwnd += (target - self.cwnd) / self.cwnd

    def _begin_epoch(self, now: float) -> None:
        self.epoch_start = now
        self.cwnd_epoch = self.cwnd
        self.w_est = self.cwnd
        if self.w_max is None or self.after_timeout:
            # No previous reduction, or first CA stage after an RTO (RFC 9438 section 4.8)
            self.w_max = self.cwnd
            self.k = 0.0
            self.after_timeout = False
        else:
            self.k = self.compute_k(self.w_max, self.cwnd_epoch, self.c)
        if self.cwnd_prior is None:
            self.cwnd_prior = self.cwnd

    def on_timeout(self, info: AckInfo) -> CCResponse:
        self.cwnd_prior = self.cwnd
        self.ssthresh = max(info.loss_flight * self.beta, MIN_SSTHRESH)
        self.cwnd = MIN_CWND
        self.in_recovery = False
        self.recover = info.snd_max - 1
        self.epoch_start = None
        self.after_timeout = True
        return CCResponse(go_back_n=True, send_kind="rto_retx",
                          events=[("cwnd_reset", f"RTO: ssthresh=beta*flight={self.ssthresh:.2f}, cwnd=1")])

    def state(self):
        s = super().state()
        s.update({"w_max": self.w_max, "K": self.k, "epoch_start": self.epoch_start,
                  "cwnd_epoch": self.cwnd_epoch, "w_est": self.w_est, "region": self.region})
        return s
