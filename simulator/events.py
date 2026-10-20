"""Timestamped event queue with a deterministic tie-breaking policy.

Events are ordered by the tuple ``(time, priority, insertion_counter)``:

1. **time** – simulated seconds; earlier events run first.
2. **priority** – for events at exactly the same instant, the ``EventType`` value
   decides.  The order is chosen so that resources are released before they are
   claimed and so that an ACK arriving at the same instant as a timer expiry is
   processed first (the timer is then recognised as stale):

   ``LINK_TX_COMPLETE < DATA_ARRIVAL < ACK_ARRIVAL < RTO_EXPIRE < CROSS_ARRIVAL < FLOW_START < SAMPLE``
3. **insertion counter** – a monotonically increasing integer, so events of the
   same type at the same time run in the order they were scheduled (FIFO).

Because no step relies on Python object identity or hash order, a run is fully
determined by its configuration and seed.
"""

from __future__ import annotations

import heapq
from enum import IntEnum
from typing import Any


class EventType(IntEnum):
    LINK_TX_COMPLETE = 0
    DATA_ARRIVAL = 1
    ACK_ARRIVAL = 2
    RTO_EXPIRE = 3
    CROSS_ARRIVAL = 4
    FLOW_START = 5
    SAMPLE = 6


class EventQueue:
    """A min-heap of ``(time, priority, counter, type, payload)`` tuples."""

    __slots__ = ("_heap", "_counter")

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, int, EventType, Any]] = []
        self._counter = 0

    def push(self, time: float, etype: EventType, payload: Any = None) -> None:
        if time != time or time < 0:  # NaN or negative
            raise ValueError(f"Cannot schedule event {etype.name} at invalid time {time!r}")
        heapq.heappush(self._heap, (time, int(etype), self._counter, etype, payload))
        self._counter += 1

    def pop(self) -> tuple[float, EventType, Any]:
        time, _prio, _cnt, etype, payload = heapq.heappop(self._heap)
        return time, etype, payload

    def peek_time(self) -> float | None:
        return self._heap[0][0] if self._heap else None

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)
