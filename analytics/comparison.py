"""Controlled multi-algorithm comparison and derived behaviour metrics.

``run_comparison`` takes one network configuration and runs it once per
algorithm, switching *every* flow to that algorithm while keeping bandwidth,
delay, buffer, loss probability, duration, flow start times and the random
seed identical.  Note that identical seeds give each flow the same stream of
random numbers, but *which* packets those draws hit still depends on how each
algorithm transmits, so loss patterns are statistically - not packet-for-
packet - identical.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from analytics.fairness import jain_index
from config import defaults as D
from config.validation import SimulationConfig
from simulator.engine import run_simulation
from simulator.metrics import RunMetrics, compute_metrics, throughput_timeseries
from simulator.trace import SimulationResult


@dataclass
class ComparisonRun:
    algorithm: str
    config: SimulationConfig
    result: SimulationResult
    metrics: RunMetrics


def run_comparison(base: SimulationConfig, algorithms: list[str],
                   progress: Callable[[int, int, str], None] | None = None,
                   runner: Callable[[SimulationConfig], SimulationResult] = run_simulation) -> list[ComparisonRun]:
    if not algorithms:
        raise ValueError("Select at least one algorithm to compare.")
    unknown = [a for a in algorithms if a not in D.ALGORITHMS]
    if unknown:
        raise ValueError(f"Unknown algorithm(s): {unknown}")
    runs = []
    for i, alg in enumerate(algorithms):
        if progress:
            progress(i, len(algorithms), alg)
        cfg = base.with_algorithm(alg).ensure_valid()
        res = runner(cfg)
        runs.append(ComparisonRun(alg, cfg, res, compute_metrics(res)))
    if progress:
        progress(len(algorithms), len(algorithms), "done")
    return runs


# ------------------------------------------------------------ recovery analysis
def recovery_episodes(result: SimulationResult, flow: int, regain_fraction: float = 0.9) -> pd.DataFrame:
    """One row per congestion response (fast retransmit or timeout) of ``flow``.

    * ``pre_cwnd``  - cwnd immediately before the response (excluding fast-recovery inflation:
                      the last value recorded outside fast recovery)
    * ``regain_s``  - time until cwnd, outside fast recovery, is back to
                      ``regain_fraction * pre_cwnd``; NaN if that does not happen before
                      the next congestion response or the end of the run.
    """
    ev = result.events
    cong = ev[(ev["flow"] == flow) & ev["event"].isin(["fast_retransmit", "timeout"])].sort_values("t")
    cw = result.cwnd[result.cwnd["flow"] == flow]
    normal = cw[cw["phase"] != "fast_recovery"]
    rows = []
    times = cong["t"].to_numpy()
    for i, (t, kind) in enumerate(zip(times, cong["event"].to_numpy())):
        before = normal[normal["t"] < t]
        if before.empty:
            continue
        pre = float(before["cwnd"].iloc[-1])
        nxt = times[i + 1] if i + 1 < len(times) else result.duration_s
        window = normal[(normal["t"] > t) & (normal["t"] <= nxt)]
        hit = window[window["cwnd"] >= regain_fraction * pre]
        regain = float(hit["t"].iloc[0] - t) if not hit.empty else math.nan
        post = cw[(cw["t"] >= t) & (cw["t"] <= nxt)]
        rows.append({"flow": flow, "t": float(t), "kind": kind, "pre_cwnd": pre,
                     "min_cwnd_after": float(post["cwnd"].min()) if not post.empty else math.nan,
                     "regain_s": regain})
    return pd.DataFrame(rows, columns=["flow", "t", "kind", "pre_cwnd", "min_cwnd_after", "regain_s"])


def startup_time(result: SimulationResult, fraction: float = 0.8) -> float:
    """First time the aggregate goodput (per bin) reaches ``fraction`` of capacity; NaN if never."""
    ts = throughput_timeseries(result)
    if ts.empty:
        return math.nan
    agg = ts.groupby("t_end")["goodput_mbps"].sum(min_count=1)
    hit = agg[agg >= fraction * result.config.bandwidth_mbps]
    return float(hit.index[0]) if len(hit) else math.nan


def fairness_over_time(result: SimulationResult, bin_s: float | None = None) -> pd.DataFrame:
    """Jain's index per time bin, computed only over bins where all flows have started."""
    ts = throughput_timeseries(result, bin_s)
    if ts.empty or result.config.n_flows < 2:
        return pd.DataFrame(columns=["t_mid", "jain"])
    piv = ts.pivot_table(index="t_mid", columns="flow", values="goodput_mbps")
    piv = piv.dropna()
    vals = [jain_index(row) if row.sum() > 0 else math.nan for row in piv.to_numpy()]
    return pd.DataFrame({"t_mid": piv.index.to_numpy(), "jain": vals})


def fairness_convergence_time(result: SimulationResult, threshold: float = 0.9, sustain_bins: int = 5) -> float:
    """Time after the last flow starts until windowed Jain >= threshold for ``sustain_bins`` bins."""
    fo = fairness_over_time(result)
    if fo.empty:
        return math.nan
    last_start = max(f.start_time_s for f in result.config.flows)
    ok = (fo["jain"] >= threshold).to_numpy()
    run = 0
    for i, flag in enumerate(ok):
        run = run + 1 if flag else 0
        if run >= sustain_bins:
            return float(fo["t_mid"].iloc[i - sustain_bins + 1] - last_start)
    return math.nan


# -------------------------------------------------------------- tables
def comparison_table(runs: list[ComparisonRun]) -> pd.DataFrame:
    rows = []
    for r in runs:
        m = r.metrics
        eps = pd.concat([recovery_episodes(r.result, f.flow) for f in m.flows], ignore_index=True)
        regain = eps["regain_s"].dropna() if not eps.empty else pd.Series(dtype=float)
        rows.append({
            "algorithm": r.algorithm,
            "goodput_mbps": m.aggregate_goodput_mbps,
            "link_util_pct": m.link_utilisation_pct,
            "loss_pct": m.loss_pct,
            "avg_rtt_ms": m.avg_rtt_ms,
            "avg_queue_pkts": m.avg_queue_pkts,
            "avg_cwnd": m.avg_cwnd,
            "fast_retransmits": m.fast_retransmits,
            "timeouts": m.timeouts,
            "retx_packets": m.retx_packets,
            "median_regain_s": float(regain.median()) if len(regain) else math.nan,
            "unrecovered_events": int(eps["regain_s"].isna().sum()) if not eps.empty else 0,
            "startup_s": startup_time(r.result),
            "jain_index": m.jain_index,
        })
    return pd.DataFrame(rows)


METRIC_INFO = {
    "goodput_mbps": ("Goodput", "Mbps", True),
    "link_util_pct": ("Link utilisation", "%", True),
    "loss_pct": ("Packet loss", "%", False),
    "avg_rtt_ms": ("Average RTT", "ms", False),
    "avg_queue_pkts": ("Average queue", "pkts", False),
    "timeouts": ("Timeouts", "", False),
    "median_regain_s": ("Median recovery time", "s", False),
    "startup_s": ("Startup time", "s", False),
    "jain_index": ("Jain's fairness", "", True),
}


def interpret(table: pd.DataFrame, config: SimulationConfig) -> list[str]:
    """Short, data-driven observations. No algorithm is assumed to win."""
    if table.empty:
        return []
    notes: list[str] = []
    label = lambda a: D.ALGORITHM_LABELS.get(a, a)  # noqa: E731
    g = table.set_index("algorithm")

    best = g["goodput_mbps"].idxmax()
    worst = g["goodput_mbps"].idxmin()
    if len(g) > 1:
        spread = g["goodput_mbps"].max() - g["goodput_mbps"].min()
        rel = spread / g["goodput_mbps"].max() * 100 if g["goodput_mbps"].max() > 0 else 0
        if rel < 3:
            notes.append(f"All algorithms reached similar goodput (within {rel:.1f}%), "
                         f"so this network does not separate them on throughput.")
        else:
            notes.append(f"{label(best)} delivered the most data ({g.loc[best, 'goodput_mbps']:.2f} Mbps); "
                         f"{label(worst)} delivered the least ({g.loc[worst, 'goodput_mbps']:.2f} Mbps), "
                         f"a {rel:.0f}% gap.")
    to = g["timeouts"]
    if to.max() > 0:
        notes.append("Retransmission timeouts occurred for " + ", ".join(
            f"{label(a)} ({int(n)})" for a, n in to.items() if n > 0) +
            ". Each timeout resets cwnd to 1 segment and waits at least the minimum RTO "
            f"({config.min_rto_s * 1000:.0f} ms), which costs far more than a fast retransmit.")
    if "median_regain_s" in g and g["median_regain_s"].notna().sum() >= 2:
        fastest = g["median_regain_s"].idxmin()
        notes.append(f"After a loss, {label(fastest)} regained 90% of its previous window fastest "
                     f"(median {g.loc[fastest, 'median_regain_s']:.2f} s).")
    if len(g) > 1 and g["avg_rtt_ms"].notna().all():
        hi = g["avg_rtt_ms"].idxmax()
        lo = g["avg_rtt_ms"].idxmin()
        if g.loc[hi, "avg_rtt_ms"] - g.loc[lo, "avg_rtt_ms"] > 0.1 * config.base_rtt_s * 1000:
            notes.append(f"{label(hi)} kept the queue fuller (average RTT {g.loc[hi, 'avg_rtt_ms']:.1f} ms vs "
                         f"{g.loc[lo, 'avg_rtt_ms']:.1f} ms for {label(lo)}): higher throughput is often bought "
                         f"with extra queueing delay.")
    if config.n_flows > 1:
        j = g["jain_index"].dropna()
        if len(j):
            notes.append(f"With {config.n_flows} competing flows, Jain's index ranged from {j.min():.3f} "
                         f"to {j.max():.3f} (1.0 = equal shares).")
    bdp = config.bdp_packets
    if config.buffer_packets < 0.5 * bdp:
        notes.append(f"The buffer ({config.buffer_packets} pkts) is well below one BDP ({bdp:.0f} pkts), so "
                     f"every multiplicative decrease briefly leaves the link idle.")
    notes.append("Caveat: these results come from a segment-level model without SACK, delayed ACKs, pacing "
                 "or HyStart; with the default Impatient NewReno timer, windows that lose many segments "
                 "often end in a timeout. Real stacks can rank the algorithms differently.")
    return notes
