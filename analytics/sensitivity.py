"""Parameter sweeps over several seeds, reported as mean +/- spread.

A single random run is anecdotal; ``run_sensitivity`` repeats every
(parameter value, algorithm) pair for several seeds and ``summarize`` reports
the mean, standard deviation, number of runs and a 95% confidence half-width
(t-distribution), so variability is visible on the chart.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace

import numpy as np
import pandas as pd

from config.validation import SimulationConfig
from simulator.engine import run_simulation
from simulator.metrics import compute_metrics

SWEEPABLE = {
    "buffer_packets": ("Buffer capacity", "packets", int),
    "delay_ms": ("One-way delay", "ms", float),
    "loss_prob": ("Random loss probability", "", float),
    "bandwidth_mbps": ("Bottleneck bandwidth", "Mbps", float),
}

RESPONSES = {
    "goodput_mbps": "Goodput (Mbps)",
    "link_util_pct": "Link utilisation (%)",
    "loss_pct": "Packet loss (%)",
    "avg_rtt_ms": "Average RTT (ms)",
    "timeouts": "Timeouts",
    "jain_index": "Jain's fairness index",
}

MAX_RUNS = 120

# two-sided 95% t quantiles for small samples (df = n - 1)
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}


def apply_param(cfg: SimulationConfig, param: str, value: float) -> SimulationConfig:
    if param not in SWEEPABLE:
        raise ValueError(f"Parameter {param!r} cannot be swept; choose from {sorted(SWEEPABLE)}")
    cast = SWEEPABLE[param][2]
    return replace(cfg, **{param: cast(value)})


def run_sensitivity(base: SimulationConfig, param: str, values: list[float], algorithms: list[str],
                    seeds: list[int], progress: Callable[[int, int], None] | None = None) -> pd.DataFrame:
    if not values or not algorithms or not seeds:
        raise ValueError("Provide at least one parameter value, algorithm and seed.")
    total = len(values) * len(algorithms) * len(seeds)
    if total > MAX_RUNS:
        raise ValueError(f"{total} runs requested; the limit is {MAX_RUNS}. Use fewer values, algorithms or seeds.")
    # validate every configuration before running anything
    configs = []
    for v in values:
        for a in algorithms:
            for s in seeds:
                cfg = replace(apply_param(base, param, v).with_algorithm(a), seed=int(s),
                              record_packet_events=False).ensure_valid()
                configs.append((v, a, s, cfg))
    rows = []
    for i, (v, a, s, cfg) in enumerate(configs):
        m = compute_metrics(run_simulation(cfg))
        row = {"param": param, "value": v, "algorithm": a, "seed": s}
        row.update(m.summary_row())
        rows.append(row)
        if progress:
            progress(i + 1, total)
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, response: str) -> pd.DataFrame:
    if response not in df.columns:
        raise ValueError(f"Unknown response {response!r}")
    g = df.groupby(["value", "algorithm"])[response]
    out = g.agg(["mean", "std", "count", "min", "max"]).reset_index()
    out["std"] = out["std"].fillna(0.0)

    def ci(row):
        n = int(row["count"])
        if n < 2:
            return math.nan
        t = _T95.get(n - 1, 1.96)
        return t * row["std"] / math.sqrt(n)

    out["ci95"] = out.apply(ci, axis=1)
    return out.sort_values(["algorithm", "value"]).reset_index(drop=True)


def parse_values(text: str, param: str) -> list[float]:
    """Parse '5, 10, 20' or a range '5:50:5' (start:stop:step, inclusive)."""
    text = text.strip()
    if not text:
        raise ValueError("Enter at least one value.")
    if ":" in text:
        parts = [float(p) for p in text.split(":")]
        if len(parts) != 3 or parts[2] <= 0 or parts[1] < parts[0]:
            raise ValueError("Use start:stop:step with step > 0 and stop >= start.")
        vals = list(np.arange(parts[0], parts[1] + parts[2] / 2, parts[2]))
    else:
        vals = [float(p) for p in text.replace(";", ",").split(",") if p.strip()]
    if param in SWEEPABLE and SWEEPABLE[param][2] is int:
        vals = [float(int(round(v))) for v in vals]
    vals = sorted(set(round(v, 10) for v in vals))
    if len(vals) > 20:
        raise ValueError("At most 20 parameter values.")
    return vals
