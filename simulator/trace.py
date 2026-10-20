"""Trace recording and the ``SimulationResult`` container.

Every number shown by the dashboard, written to an export or used for ML is
derived from the tables recorded here.

Tables (pandas DataFrames on the result):

``events``      t, event, flow, seq, uid, info, cwnd, ssthresh, queue
                Congestion-control events, drops and retransmissions are always
                recorded.  Per-packet events (send of new data, enqueue,
                tx_start, tx_end, rx, ack_rx) are recorded only when
                ``record_packet_events`` is true.
``cwnd``        t, flow, cwnd, ssthresh, phase   (one row per change)
``queue``       t, queue                          (one row per change in occupancy)
``rtt``         t, flow, rtt_ms                   (one row per ACK whose triggering
                                                   segment was not a retransmission)
``deliveries``  t, flow, segments, bytes          (in-order, unique data handed to the application)
``link``        t, flow, bytes, is_retx           (every completed serialization on the bottleneck)
``samples``     periodic snapshot per flow (see SAMPLE_COLUMNS)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# Event names --------------------------------------------------------------------
EV_FLOW_START = "flow_start"
EV_SEND = "send"
EV_ENQUEUE = "enqueue"
EV_TX_START = "tx_start"
EV_TX_END = "tx_end"
EV_DROP = "drop"
EV_RX = "rx"
EV_ACK_RX = "ack_rx"
EV_FAST_RETRANSMIT = "fast_retransmit"
EV_ENTER_RECOVERY = "enter_recovery"
EV_EXIT_RECOVERY = "exit_recovery"
EV_PARTIAL_ACK = "partial_ack"
EV_TIMEOUT = "timeout"
EV_CWND_RESET = "cwnd_reset"
EV_PHASE_CHANGE = "phase_change"

PACKET_EVENTS = {EV_SEND, EV_ENQUEUE, EV_TX_START, EV_TX_END, EV_RX, EV_ACK_RX}
CC_EVENTS = {EV_FAST_RETRANSMIT, EV_ENTER_RECOVERY, EV_EXIT_RECOVERY, EV_PARTIAL_ACK, EV_TIMEOUT,
             EV_CWND_RESET, EV_PHASE_CHANGE, EV_FLOW_START}

DROP_OVERFLOW = "overflow"
DROP_RANDOM = "random"
DROP_BURST = "burst"
DROP_FORCED = "forced"
DROP_TYPES = (DROP_OVERFLOW, DROP_RANDOM, DROP_BURST, DROP_FORCED)

EVENT_COLUMNS = ["t", "event", "flow", "seq", "uid", "info", "cwnd", "ssthresh", "queue"]
CWND_COLUMNS = ["t", "flow", "cwnd", "ssthresh", "phase"]
SAMPLE_COLUMNS = [
    "t", "flow", "cwnd", "ssthresh", "phase", "queue", "snd_una", "snd_max", "delivered_segments",
    "sent_packets", "retx_packets", "drops", "overflow_drops", "dupacks", "timeouts", "fast_retransmits",
    "srtt_ms", "rtt_count", "rtt_sum_ms", "rtt_sq_sum_ms", "link_bytes_total", "overflow_drops_total",
]


class TraceRecorder:
    """Append-only lists; converted to DataFrames once at the end of a run."""

    def __init__(self, record_packet_events: bool = True) -> None:
        self.record_packet_events = record_packet_events
        self.events: list[tuple] = []
        self.cwnd: list[tuple] = []
        self.queue: list[tuple] = [(0.0, 0)]
        self.rtt: list[tuple] = []
        self.deliveries: list[tuple] = []
        self.link: list[tuple] = []
        self.samples: list[tuple] = []

    def event(self, t: float, event: str, flow: int, seq: int = -1, uid: int = -1, info: str = "",
              cwnd: float = float("nan"), ssthresh: float = float("nan"), queue: int = -1) -> None:
        self.events.append((t, event, flow, seq, uid, info, cwnd, ssthresh, queue))


@dataclass
class SimulationResult:
    config: Any                       # SimulationConfig (kept untyped to avoid an import cycle)
    events: pd.DataFrame
    cwnd: pd.DataFrame
    queue: pd.DataFrame
    rtt: pd.DataFrame
    deliveries: pd.DataFrame
    link: pd.DataFrame
    samples: pd.DataFrame
    flow_stats: list[dict[str, Any]]
    run_info: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return float(self.config.duration_s)

    def events_of(self, *names: str, flow: int | None = None) -> pd.DataFrame:
        df = self.events[self.events["event"].isin(names)]
        if flow is not None:
            df = df[df["flow"] == flow]
        return df


def build_result(config: Any, rec: TraceRecorder, flow_stats: list[dict[str, Any]],
                 run_info: dict[str, Any]) -> SimulationResult:
    mss = config.mss_bytes
    events = pd.DataFrame(rec.events, columns=EVENT_COLUMNS)
    cwnd = pd.DataFrame(rec.cwnd, columns=CWND_COLUMNS)
    queue = pd.DataFrame(rec.queue, columns=["t", "queue"])
    rtt = pd.DataFrame(rec.rtt, columns=["t", "flow", "rtt_s"])
    rtt["rtt_ms"] = rtt["rtt_s"] * 1000.0
    rtt = rtt.drop(columns=["rtt_s"])
    deliveries = pd.DataFrame(rec.deliveries, columns=["t", "flow", "segments"])
    deliveries["bytes"] = deliveries["segments"] * mss
    link = pd.DataFrame(rec.link, columns=["t", "flow", "bytes", "is_retx"])
    samples = pd.DataFrame(rec.samples, columns=SAMPLE_COLUMNS)
    return SimulationResult(config=config, events=events, cwnd=cwnd, queue=queue, rtt=rtt,
                            deliveries=deliveries, link=link, samples=samples,
                            flow_stats=flow_stats, run_info=run_info)
