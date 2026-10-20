"""Network elements: the bottleneck link with a FIFO drop-tail buffer, and receivers.

Bottleneck model
----------------
* The link serialises one packet at a time at ``bandwidth_bps``.
  Serialization time = ``size_bytes * 8 / bandwidth_bps``.
* ``buffer_packets`` is the number of packets that may *wait* in the FIFO
  buffer.  The packet currently being serialised is not counted as waiting.
* Drop-tail: a packet that arrives while the link is busy and the buffer holds
  ``buffer_packets`` packets is dropped ("overflow").
* After serialization the packet propagates for ``delay_s`` to the receiver.

These classes hold state only; the engine schedules the events.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from simulator.packets import DataPacket


class BottleneckLink:
    __slots__ = ("bandwidth_bps", "delay_s", "capacity", "queue", "in_service", "max_occupancy_seen")

    def __init__(self, bandwidth_bps: float, delay_s: float, buffer_packets: int) -> None:
        if bandwidth_bps <= 0:
            raise ValueError("bandwidth must be positive")
        if buffer_packets < 1:
            raise ValueError("buffer must hold at least one packet")
        self.bandwidth_bps = bandwidth_bps
        self.delay_s = delay_s
        self.capacity = buffer_packets
        self.queue: deque[DataPacket] = deque()
        self.in_service: DataPacket | None = None
        self.max_occupancy_seen = 0

    # ------------------------------------------------------------------ helpers
    def tx_time(self, pkt: DataPacket) -> float:
        return pkt.size_bytes * 8.0 / self.bandwidth_bps

    @property
    def occupancy(self) -> int:
        """Packets waiting in the buffer (excludes the packet being serialised)."""
        return len(self.queue)

    @property
    def busy(self) -> bool:
        return self.in_service is not None

    # ---------------------------------------------------------------- operations
    def offer(self, pkt: DataPacket, now: float) -> str:
        """A packet arrives at the bottleneck.

        Returns ``"tx"`` if it starts transmission immediately, ``"queued"`` if it
        waits in the buffer, or ``"dropped"`` if the buffer is full.
        """
        pkt.enqueued_at = now
        if self.in_service is None:
            self.in_service = pkt
            pkt.tx_start_at = now
            return "tx"
        if len(self.queue) >= self.capacity:
            return "dropped"
        self.queue.append(pkt)
        if len(self.queue) > self.max_occupancy_seen:
            self.max_occupancy_seen = len(self.queue)
        return "queued"

    def complete(self, now: float) -> tuple[DataPacket, DataPacket | None]:
        """Finish serialising the in-service packet and start the next one (if any)."""
        done = self.in_service
        if done is None:
            raise RuntimeError("link completion event with no packet in service")
        nxt = self.queue.popleft() if self.queue else None
        self.in_service = nxt
        if nxt is not None:
            nxt.tx_start_at = now
        return done, nxt


@dataclass
class Receiver:
    """Cumulative-ACK receiver with an out-of-order buffer (no SACK, no delayed ACKs).

    Every arriving data segment immediately triggers one ACK carrying ``rcv_nxt``.
    In-order data is delivered to the application exactly once.
    """

    flow_id: int
    rcv_nxt: int = 0
    out_of_order: set[int] = field(default_factory=set)
    duplicates: int = 0
    delivered_segments: int = 0

    def receive(self, seq: int) -> tuple[str, int]:
        """Process segment ``seq``.

        Returns ``(classification, newly_delivered_segments)`` where
        classification is ``"in_order"``, ``"out_of_order"`` or ``"duplicate"``.
        """
        if seq < self.rcv_nxt or seq in self.out_of_order:
            self.duplicates += 1
            return "duplicate", 0
        if seq > self.rcv_nxt:
            self.out_of_order.add(seq)
            return "out_of_order", 0
        # seq == rcv_nxt: deliver it plus any contiguous buffered segments
        advanced = 1
        self.rcv_nxt += 1
        while self.rcv_nxt in self.out_of_order:
            self.out_of_order.remove(self.rcv_nxt)
            self.rcv_nxt += 1
            advanced += 1
        self.delivered_segments += advanced
        return "in_order", advanced
