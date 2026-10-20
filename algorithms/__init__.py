"""Congestion control algorithm registry."""

from __future__ import annotations

from algorithms.base import AckInfo, CCResponse, CongestionControl
from algorithms.cubic import CubicCC
from algorithms.newreno import NewRenoCC
from algorithms.reno import RenoCC
from algorithms.tahoe import TahoeCC

REGISTRY: dict[str, type[CongestionControl]] = {
    "tahoe": TahoeCC,
    "reno": RenoCC,
    "newreno": NewRenoCC,
    "cubic": CubicCC,
}


def create_algorithm(name: str, initial_cwnd: float, initial_ssthresh: float, *,
                     cubic_c: float = 0.4, cubic_beta: float = 0.7,
                     cubic_fast_convergence: bool = True,
                     newreno_timer_variant: str = "impatient") -> CongestionControl:
    try:
        cls = REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown congestion control algorithm {name!r}; choose from {sorted(REGISTRY)}") from exc
    if cls is CubicCC:
        return CubicCC(initial_cwnd, initial_ssthresh, c=cubic_c, beta=cubic_beta,
                       fast_convergence=cubic_fast_convergence, timer_variant=newreno_timer_variant)
    if cls is NewRenoCC:
        return NewRenoCC(initial_cwnd, initial_ssthresh, timer_variant=newreno_timer_variant)
    return cls(initial_cwnd, initial_ssthresh)


__all__ = ["AckInfo", "CCResponse", "CongestionControl", "TahoeCC", "RenoCC", "NewRenoCC", "CubicCC",
           "REGISTRY", "create_algorithm"]
