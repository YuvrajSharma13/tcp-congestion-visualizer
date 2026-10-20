"""Common interface for congestion control algorithms.

The *sender* (simulator/flow.py) owns sequence-number bookkeeping, duplicate-ACK
counting, the retransmission timer and the actual transmission of packets.  An
*algorithm* owns ``cwnd``, ``ssthresh`` and its recovery state, and tells the
sender what to do through a ``CCResponse``.

All window quantities are in **segments** (floats).  The sender may transmit
while ``snd_nxt - snd_una < min(floor(cwnd), rwnd)``.

Shared rules (RFC 5681):
* slow start (cwnd < ssthresh): cwnd += 1 per ACK of new data
* congestion avoidance (cwnd >= ssthresh): cwnd += 1/cwnd per ACK of new data
* loss: ssthresh = max(FlightSize / 2, 2)  (RFC 5681 eq. 4)

``loss_flight`` is the FlightSize used in the loss response.  It equals the RFC
FlightSize (snd_max - snd_una) minus the segments that duplicate ACKs from an
*earlier* hole have already shown to be at the receiver (the duplicate-ACK
"SACK emulation" Linux uses for non-SACK flows).  For an isolated loss it is
exactly the RFC value; it only differs after a recovery episode that sent new
data, where snd_max - snd_una would count hundreds of segments that already
arrived and would set ssthresh far above the path capacity.

``recover`` (RFC 6582) holds the highest segment number that was outstanding
when the last loss response happened.  A fast retransmit is only allowed when
the duplicate ACKs' cumulative ACK is greater than ``recover``; this prevents a
second, spurious reduction triggered by duplicate ACKs that belong to data sent
before the previous loss response (e.g. after a go-back-N retransmission).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from config import defaults as D

MIN_CWND = 1.0
MIN_SSTHRESH = 2.0

PHASE_SLOW_START = "slow_start"
PHASE_CONGESTION_AVOIDANCE = "congestion_avoidance"
PHASE_FAST_RECOVERY = "fast_recovery"


@dataclass(slots=True)
class AckInfo:
    """Information handed to an algorithm with each ACK or timeout."""

    now: float
    ack: int               # cumulative ACK number (next expected segment)
    newly_acked: int       # segments newly acknowledged by this ACK (0 for a duplicate)
    flight_size: int       # RFC FlightSize: segments outstanding after this ACK (snd_max - snd_una)
    loss_flight: int       # FlightSize used for the loss response (see module docstring)
    snd_max: int           # one past the highest segment ever sent
    srtt: float | None     # smoothed RTT in seconds (None before the first sample)
    min_rtt: float | None  # smallest RTT sample so far, seconds


@dataclass(slots=True)
class CCResponse:
    """Instructions returned by an algorithm to the sender."""

    retransmit_head: bool = False  # retransmit segment snd_una now, regardless of the window
    go_back_n: bool = False        # set snd_nxt = snd_una (resend everything from the hole)
    restart_timer: bool = True     # for new ACKs: restart the RTO timer (RFC 6298 rule 5.3)
    send_kind: str = ""            # label for the retransmission this response causes
    events: list[tuple[str, str]] = field(default_factory=list)  # (event, detail) for the log


class CongestionControl(ABC):
    """Base class shared by Tahoe, Reno, NewReno and CUBIC."""

    name: str = "base"
    label: str = "Base"

    def __init__(self, initial_cwnd: float = D.DEFAULT_INITIAL_CWND,
                 initial_ssthresh: float = D.DEFAULT_INITIAL_SSTHRESH) -> None:
        if initial_cwnd < MIN_CWND:
            raise ValueError("initial cwnd must be at least 1 segment")
        self.cwnd: float = float(initial_cwnd)
        self.ssthresh: float = max(float(initial_ssthresh), MIN_SSTHRESH)
        self.in_recovery: bool = False
        self.recover: int = -1

    # ------------------------------------------------------------------ queries
    @property
    def phase(self) -> str:
        if self.in_recovery:
            return PHASE_FAST_RECOVERY
        if self.cwnd < self.ssthresh:
            return PHASE_SLOW_START
        return PHASE_CONGESTION_AVOIDANCE

    def state(self) -> dict[str, float | str | bool | None]:
        """Snapshot of algorithm state for inspection (playback, tests)."""
        return {"cwnd": self.cwnd, "ssthresh": self.ssthresh, "phase": self.phase,
                "in_recovery": self.in_recovery, "recover": self.recover}

    # ------------------------------------------------------------------ events
    @abstractmethod
    def on_new_ack(self, info: AckInfo) -> CCResponse:
        """ACK that advances snd_una."""

    @abstractmethod
    def on_dupack(self, info: AckInfo, dupacks: int) -> CCResponse:
        """Duplicate ACK; ``dupacks`` is the count of consecutive duplicates (1, 2, 3, ...)."""

    def on_timeout(self, info: AckInfo) -> CCResponse:
        """RFC 5681 (eq. 4) + RFC 6582 section 4.1 behaviour shared by the loss-based algorithms."""
        self.ssthresh = self._loss_ssthresh(info.loss_flight)
        self.cwnd = MIN_CWND
        self.in_recovery = False
        self.recover = info.snd_max - 1
        return CCResponse(go_back_n=True, send_kind="rto_retx",
                          events=[("cwnd_reset", f"RTO: ssthresh={self.ssthresh:.2f}, cwnd=1")])

    # ----------------------------------------------------------------- helpers
    def _loss_ssthresh(self, flight: int) -> float:
        return max(flight / 2.0, MIN_SSTHRESH)

    def _can_fast_retransmit(self, ack: int) -> bool:
        return ack > self.recover

    def _grow(self, info: AckInfo) -> None:
        """Standard RFC 5681 growth: +1 per ACK in slow start, +1/cwnd in congestion avoidance."""
        if self.cwnd < self.ssthresh:
            self.cwnd += 1.0
        else:
            self.cwnd += 1.0 / self.cwnd

    def _clamp(self) -> None:
        if self.cwnd < MIN_CWND:
            self.cwnd = MIN_CWND
        if self.ssthresh < MIN_SSTHRESH:
            self.ssthresh = MIN_SSTHRESH
