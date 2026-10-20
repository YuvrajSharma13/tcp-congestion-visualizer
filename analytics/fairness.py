"""Jain's fairness index (Jain, Chiu & Hawe, DEC TR-301, 1984).

    J(x) = (sum x_i)^2 / (n * sum x_i^2)

J ranges from 1/n (one flow gets everything) to 1 (perfectly equal shares).
It measures *equality* of the allocation, not efficiency: two flows that each
get 1 Mbps on a 100 Mbps link are perfectly fair (J = 1) and very inefficient.
"""

from __future__ import annotations

import math
from collections.abc import Iterable


def jain_index(values: Iterable[float]) -> float:
    """Return Jain's index, or NaN when it is undefined.

    * empty input -> NaN (no flows)
    * all values zero -> NaN (0/0: no allocation to compare)
    * negative or non-finite values -> ValueError
    """
    xs = [float(v) for v in values]
    if not xs:
        return math.nan
    for v in xs:
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"Throughput values must be finite and non-negative (got {v}).")
    s = sum(xs)
    sq = sum(v * v for v in xs)
    if sq == 0.0:
        return math.nan
    return (s * s) / (len(xs) * sq)


def fairness_label(j: float) -> str:
    if j != j:  # NaN
        return "undefined"
    if j >= 0.95:
        return "very fair"
    if j >= 0.8:
        return "moderately fair"
    if j >= 0.6:
        return "unfair"
    return "very unfair"
