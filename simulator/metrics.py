"""Performance metrics computed from a ``SimulationResult``.

Definitions (also in docs/simulation_assumptions.md):

Goodput / average throughput (Mbps)
    Unique, in-order payload bytes delivered to the receiving application
    (``deliveries`` table) x 8 / active time.  A flow's active time is from its
    start time to the end of the run.  Retransmitted copies and duplicates
    never count, so retransmissions cannot inflate goodput.
Aggregate goodput (Mbps)
    Sum of all flows' delivered bytes x 8 / run duration.
Link utilisation (%)
    Bytes whose serialization completed on the bottleneck (TCP data including
    retransmissions, plus cross traffic, plus packets later lost on the wire)
    x 8 / (capacity x duration) x 100.  It measures how busy the link was and
    cannot exceed 100 %.
Goodput utilisation (%)
    Aggregate TCP goodput / capacity x 100.
Packet loss (%)
    Dropped TCP data packets (overflow + random + burst + forced) / TCP data
    packets transmitted (including retransmissions) x 100.
RTT (ms)
    One sample per ACK whose triggering segment was not a retransmission
    (Karn): time from sending the segment to receiving its ACK.  Includes
    serialization, propagation and queueing delay.
Average congestion window
    Time-weighted mean of the step function cwnd(t) over the flow's active
    time; peak = maximum value reached (includes fast-recovery inflation).
Queue occupancy
    Packets waiting in the bottleneck buffer; the average is time-weighted.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from analytics.fairness import jain_index
from simulator.trace import DROP_TYPES, SimulationResult


def _nan_to_none(x: float) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


@dataclass
class FlowMetrics:
    flow: int
    algorithm: str
    start_time_s: float
    active_duration_s: float
    delivered_bytes: int
    goodput_mbps: float
    sent_packets: int
    retx_packets: int
    retx_bytes: int
    drops: int
    loss_pct: float
    timeouts: int
    fast_retransmits: int
    partial_acks: int
    avg_rtt_ms: float
    rtt_std_ms: float
    min_rtt_ms: float
    p95_rtt_ms: float
    avg_cwnd: float
    peak_cwnd: float
    drops_by_type: dict[str, int] = field(default_factory=dict)


@dataclass
class RunMetrics:
    duration_s: float
    n_flows: int
    algorithms: list[str]
    capacity_mbps: float
    aggregate_goodput_mbps: float
    link_utilisation_pct: float
    goodput_utilisation_pct: float
    tcp_packets_sent: int
    tcp_drops: int
    loss_pct: float
    drops_by_type: dict[str, int]
    retx_packets: int
    timeouts: int
    fast_retransmits: int
    avg_rtt_ms: float
    rtt_std_ms: float
    avg_queue_pkts: float
    max_queue_pkts: int
    avg_cwnd: float
    peak_cwnd: float
    jain_index: float
    bdp_packets: float
    base_rtt_ms: float
    flows: list[FlowMetrics]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return _json_safe(d)

    def summary_row(self) -> dict[str, Any]:
        """Flat dict used in tables, history and CSV."""
        return {
            "algorithms": "+".join(self.algorithms),
            "flows": self.n_flows,
            "goodput_mbps": self.aggregate_goodput_mbps,
            "link_util_pct": self.link_utilisation_pct,
            "goodput_util_pct": self.goodput_utilisation_pct,
            "loss_pct": self.loss_pct,
            "drops": self.tcp_drops,
            "retx_packets": self.retx_packets,
            "timeouts": self.timeouts,
            "fast_retransmits": self.fast_retransmits,
            "avg_rtt_ms": self.avg_rtt_ms,
            "rtt_std_ms": self.rtt_std_ms,
            "avg_queue_pkts": self.avg_queue_pkts,
            "max_queue_pkts": self.max_queue_pkts,
            "avg_cwnd": self.avg_cwnd,
            "peak_cwnd": self.peak_cwnd,
            "jain_index": self.jain_index,
        }


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    return obj


# ------------------------------------------------------------------- helpers
def time_weighted_mean(times: np.ndarray, values: np.ndarray, t0: float, t1: float) -> float:
    """Mean of a right-continuous step function given by (times, values) over [t0, t1].

    The value before the first change point is taken to be values[0].
    Returns NaN if the interval is empty or there are no points.
    """
    if t1 <= t0 or len(times) == 0:
        return math.nan
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    # value in force at t0
    idx0 = np.searchsorted(times, t0, side="right") - 1
    start_val = values[max(idx0, 0)]
    mask = (times > t0) & (times < t1)
    ts = np.concatenate(([t0], times[mask], [t1]))
    vs = np.concatenate(([start_val], values[mask]))
    widths = np.diff(ts)
    return float(np.sum(widths * vs) / (t1 - t0))


def _safe_pct(num: float, den: float) -> float:
    return float(num) / float(den) * 100.0 if den else 0.0


# -------------------------------------------------------------------- metrics
def compute_flow_metrics(result: SimulationResult) -> list[FlowMetrics]:
    cfg = result.config
    T = result.duration_s
    out: list[FlowMetrics] = []
    deliv = result.deliveries
    rtt = result.rtt
    cw = result.cwnd
    for st in result.flow_stats:
        f = st["flow"]
        start = float(st["start_time_s"])
        active = max(T - start, 0.0)
        d_bytes = int(deliv.loc[deliv["flow"] == f, "bytes"].sum()) if len(deliv) else 0
        goodput = d_bytes * 8.0 / active / 1e6 if active > 0 else 0.0
        r = rtt.loc[rtt["flow"] == f, "rtt_ms"].to_numpy() if len(rtt) else np.array([])
        c = cw[cw["flow"] == f]
        if len(c) and active > 0:
            avg_cwnd = time_weighted_mean(c["t"].to_numpy(), c["cwnd"].to_numpy(), start, T)
            peak = float(c["cwnd"].max())
        else:
            avg_cwnd, peak = math.nan, math.nan
        sent = int(st["sent_packets"])
        out.append(FlowMetrics(
            flow=f, algorithm=st["algorithm"], start_time_s=start, active_duration_s=active,
            delivered_bytes=d_bytes, goodput_mbps=goodput, sent_packets=sent,
            retx_packets=int(st["retx_packets"]), retx_bytes=int(st["retx_packets"]) * cfg.mss_bytes,
            drops=int(st["drops"]), loss_pct=_safe_pct(st["drops"], sent),
            timeouts=int(st["timeouts"]), fast_retransmits=int(st["fast_retransmits"]),
            partial_acks=int(st["partial_acks"]),
            avg_rtt_ms=float(r.mean()) if r.size else math.nan,
            rtt_std_ms=float(r.std()) if r.size else math.nan,
            min_rtt_ms=float(r.min()) if r.size else math.nan,
            p95_rtt_ms=float(np.percentile(r, 95)) if r.size else math.nan,
            avg_cwnd=avg_cwnd, peak_cwnd=peak,
            drops_by_type={k: int(st.get(f"drops_{k}", 0)) for k in DROP_TYPES},
        ))
    return out


def compute_metrics(result: SimulationResult) -> RunMetrics:
    cfg = result.config
    T = result.duration_s
    flows = compute_flow_metrics(result)
    cap_bits = cfg.bandwidth_bps * T
    link_bits = float(result.link["bytes"].sum()) * 8.0 if len(result.link) else 0.0
    total_deliv_bits = sum(fm.delivered_bytes for fm in flows) * 8.0
    sent = sum(fm.sent_packets for fm in flows)
    drops = sum(fm.drops for fm in flows)
    drops_by_type = {k: sum(fm.drops_by_type.get(k, 0) for fm in flows) for k in DROP_TYPES}
    rtt = result.rtt["rtt_ms"].to_numpy() if len(result.rtt) else np.array([])
    q = result.queue
    avg_q = time_weighted_mean(q["t"].to_numpy(), q["queue"].to_numpy(), 0.0, T) if len(q) else math.nan
    cw_avgs = [fm.avg_cwnd for fm in flows if not math.isnan(fm.avg_cwnd)]
    cw_peaks = [fm.peak_cwnd for fm in flows if not math.isnan(fm.peak_cwnd)]
    return RunMetrics(
        duration_s=T,
        n_flows=len(flows),
        algorithms=[fm.algorithm for fm in flows],
        capacity_mbps=cfg.bandwidth_mbps,
        aggregate_goodput_mbps=total_deliv_bits / T / 1e6 if T > 0 else 0.0,
        link_utilisation_pct=min(_safe_pct(link_bits, cap_bits), 100.0),
        goodput_utilisation_pct=_safe_pct(total_deliv_bits, cap_bits),
        tcp_packets_sent=sent,
        tcp_drops=drops,
        loss_pct=_safe_pct(drops, sent),
        drops_by_type=drops_by_type,
        retx_packets=sum(fm.retx_packets for fm in flows),
        timeouts=sum(fm.timeouts for fm in flows),
        fast_retransmits=sum(fm.fast_retransmits for fm in flows),
        avg_rtt_ms=float(rtt.mean()) if rtt.size else math.nan,
        rtt_std_ms=float(rtt.std()) if rtt.size else math.nan,
        avg_queue_pkts=avg_q,
        max_queue_pkts=int(q["queue"].max()) if len(q) else 0,
        avg_cwnd=float(np.mean(cw_avgs)) if cw_avgs else math.nan,
        peak_cwnd=float(np.max(cw_peaks)) if cw_peaks else math.nan,
        jain_index=jain_index([fm.goodput_mbps for fm in flows]) if flows else math.nan,
        bdp_packets=cfg.bdp_packets,
        base_rtt_ms=cfg.base_rtt_s * 1000.0,
        flows=flows,
    )


def flow_metrics_frame(m: RunMetrics) -> pd.DataFrame:
    rows = []
    for fm in m.flows:
        d = asdict(fm)
        dbt = d.pop("drops_by_type")
        d.update({f"drops_{k}": v for k, v in dbt.items()})
        rows.append(d)
    return pd.DataFrame(rows)


# --------------------------------------------------------------- time series
def default_bin_s(result: SimulationResult) -> float:
    """Bin width for throughput plots: about 200 bins, at least one base RTT, at least 10 ms."""
    cfg = result.config
    return max(result.duration_s / 200.0, cfg.base_rtt_s, 0.01)


def throughput_timeseries(result: SimulationResult, bin_s: float | None = None) -> pd.DataFrame:
    """Goodput per flow per time bin (Mbps).

    The final bin may be shorter than ``bin_s``; its rate is computed over its
    actual width, so an incomplete last interval is not under-reported.
    Returns columns: t_start, t_end, t_mid, flow, goodput_mbps.
    """
    T = result.duration_s
    bin_s = bin_s or default_bin_s(result)
    if bin_s <= 0:
        raise ValueError("bin width must be positive")
    edges = np.arange(0.0, T, bin_s)
    edges = np.append(edges, T)
    widths = np.diff(edges)
    frames = []
    d = result.deliveries
    for st in result.flow_stats:
        f = st["flow"]
        sub = d[d["flow"] == f]
        counts, _ = np.histogram(sub["t"].to_numpy(), bins=edges, weights=sub["bytes"].to_numpy())
        rate = counts * 8.0 / widths / 1e6
        before_start = edges[1:] <= st["start_time_s"]
        rate = np.where(before_start, np.nan, rate)
        frames.append(pd.DataFrame({"t_start": edges[:-1], "t_end": edges[1:],
                                    "t_mid": (edges[:-1] + edges[1:]) / 2.0, "flow": f, "goodput_mbps": rate}))
    if not frames:
        return pd.DataFrame(columns=["t_start", "t_end", "t_mid", "flow", "goodput_mbps"])
    return pd.concat(frames, ignore_index=True)


def link_utilisation_timeseries(result: SimulationResult, bin_s: float | None = None) -> pd.DataFrame:
    T = result.duration_s
    bin_s = bin_s or default_bin_s(result)
    edges = np.append(np.arange(0.0, T, bin_s), T)
    widths = np.diff(edges)
    lk = result.link
    counts, _ = np.histogram(lk["t"].to_numpy(), bins=edges, weights=lk["bytes"].to_numpy()) if len(lk) \
        else (np.zeros(len(widths)), None)
    util = counts * 8.0 / (widths * result.config.bandwidth_bps) * 100.0
    return pd.DataFrame({"t_mid": (edges[:-1] + edges[1:]) / 2.0, "util_pct": np.minimum(util, 100.0)})
