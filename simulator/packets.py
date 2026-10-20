"""Packet and acknowledgement records.

Sequence numbers count *segments* (0, 1, 2, ...), not bytes.  Every data
segment carries exactly one MSS of payload.  An ACK carries the cumulative
acknowledgement number ``ack`` = the next segment the receiver expects
(``rcv_nxt``), like TCP's byte-based ACK field.
"""

from __future__ import annotations

from dataclasses import dataclass

CROSS_FLOW_ID = -1
"""flow_id used for unresponsive cross-traffic packets."""


@dataclass(slots=True)
class DataPacket:
    uid: int            # unique id of this *transmission* (a retransmission gets a new uid)
    flow_id: int        # CROSS_FLOW_ID for cross traffic
    seq: int            # segment number (-1 for cross traffic)
    size_bytes: int
    sent_at: float      # time the sender handed the packet to the bottleneck
    is_retx: bool       # True when seq had already been transmitted before
    send_kind: str      # "new", "fast_retx", "partial_retx", "rto_retx", "gbn_retx", "cross"
    enqueued_at: float = -1.0
    tx_start_at: float = -1.0


@dataclass(slots=True)
class AckPacket:
    flow_id: int
    ack: int            # cumulative ACK: next expected segment
    trigger_seq: int    # segment whose arrival generated this ACK
    trigger_uid: int
    echo_sent_at: float # sender timestamp of the triggering transmission (like TSecr)
    echo_is_retx: bool  # whether the triggering transmission was a retransmission (Karn)
    sent_at: float
