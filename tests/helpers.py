"""Shared helpers for the test-suite."""

from __future__ import annotations

from algorithms.base import AckInfo


def info(ack: int = 0, newly: int = 0, flight: int = 10, snd_max: int | None = None, now: float = 0.0,
         srtt: float | None = 0.1, loss_flight: int | None = None, min_rtt: float | None = 0.1) -> AckInfo:
    """Build an AckInfo for unit-testing algorithms without the engine."""
    return AckInfo(now=now, ack=ack, newly_acked=newly, flight_size=flight,
                   loss_flight=flight if loss_flight is None else loss_flight,
                   snd_max=ack + flight if snd_max is None else snd_max, srtt=srtt, min_rtt=min_rtt)
