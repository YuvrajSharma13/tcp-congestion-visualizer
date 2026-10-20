"""CSV exports built directly from simulation output."""

from __future__ import annotations

import io

import pandas as pd

from simulator.metrics import RunMetrics, flow_metrics_frame, throughput_timeseries
from simulator.trace import SimulationResult


def _to_csv(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue().encode("utf-8")


def events_csv(result: SimulationResult) -> bytes:
    """Event log: t, event, flow, seq, uid, info, cwnd, ssthresh, queue."""
    return _to_csv(result.events)


def cwnd_csv(result: SimulationResult) -> bytes:
    return _to_csv(result.cwnd)


def metrics_csv(metrics: RunMetrics, run_id: str = "") -> bytes:
    """One row per flow plus an 'all' row with aggregate metrics."""
    per_flow = flow_metrics_frame(metrics)
    agg = {"flow": "all", "algorithm": "+".join(metrics.algorithms),
           "goodput_mbps": metrics.aggregate_goodput_mbps, "loss_pct": metrics.loss_pct,
           "drops": metrics.tcp_drops, "sent_packets": metrics.tcp_packets_sent,
           "retx_packets": metrics.retx_packets, "timeouts": metrics.timeouts,
           "fast_retransmits": metrics.fast_retransmits, "avg_rtt_ms": metrics.avg_rtt_ms,
           "rtt_std_ms": metrics.rtt_std_ms, "avg_cwnd": metrics.avg_cwnd, "peak_cwnd": metrics.peak_cwnd,
           "link_utilisation_pct": metrics.link_utilisation_pct,
           "goodput_utilisation_pct": metrics.goodput_utilisation_pct,
           "avg_queue_pkts": metrics.avg_queue_pkts, "max_queue_pkts": metrics.max_queue_pkts,
           "jain_index": metrics.jain_index}
    df = pd.concat([per_flow, pd.DataFrame([agg])], ignore_index=True)
    if run_id:
        df.insert(0, "run_id", run_id)
    return _to_csv(df)


def timeseries_csv(result: SimulationResult) -> bytes:
    """Periodic samples per flow (cwnd, ssthresh, queue, counters) - the table used for ML features."""
    return _to_csv(result.samples)


def throughput_csv(result: SimulationResult, bin_s: float | None = None) -> bytes:
    return _to_csv(throughput_timeseries(result, bin_s))


def table_csv(df: pd.DataFrame) -> bytes:
    return _to_csv(df)
