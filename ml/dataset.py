"""Leakage-safe dataset for near-future congestion prediction.

Prediction task
---------------
At time t, using only telemetry observed in the window (t - W, t], predict
whether **at least one buffer-overflow drop happens at the bottleneck in the
interval (t, t + H]** (H = prediction horizon).

* Features are computed by ``features_from_series`` from samples with time <= t
  only (it never looks at later rows - see tests/test_ml.py).
* Labels are computed separately by ``labels_from_series`` from the cumulative
  overflow counter at t and t + H.
* Every row carries ``run_id`` and ``config_id``; training/evaluation splits are
  made by ``config_id`` so overlapping windows from the same network never
  appear on both sides.

Features are normalised by the configuration (buffer, BDP, capacity, base RTT)
so one model can be applied to networks of different sizes.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from config import defaults as D
from config.validation import SimulationConfig, make_config
from simulator.engine import run_simulation
from simulator.trace import SimulationResult

FEATURES = [
    "queue_frac",          # queue / buffer at t
    "queue_mean_frac",     # mean queue / buffer over the window
    "queue_trend",         # (queue(t) - queue(t-W)) / buffer
    "rtt_ratio",           # mean RTT in window / base RTT
    "rtt_std_ratio",       # RTT standard deviation in window / base RTT
    "loss_recent",         # drops in window / packets sent in window
    "retx_rate",           # retransmissions in window / packets sent in window
    "dupack_rate",         # duplicate ACKs in window / packets sent in window
    "cwnd_pipe_ratio",     # sum of cwnd / (BDP + buffer)
    "cwnd_growth",         # change of sum cwnd over the window / (BDP + buffer)
    "throughput_trend",    # (goodput second half - first half of window) / capacity
    "utilisation",         # link busy fraction over the window
    "recovery_frac",       # fraction of flows in fast recovery at t
    "slow_start_frac",     # fraction of flows in slow start at t
]

FEATURE_LABELS = {
    "queue_frac": "Queue occupancy (fraction of buffer)",
    "queue_mean_frac": "Average queue over window",
    "queue_trend": "Queue trend over window",
    "rtt_ratio": "RTT inflation (RTT / base RTT)",
    "rtt_std_ratio": "RTT variation",
    "loss_recent": "Recent loss rate",
    "retx_rate": "Recent retransmission rate",
    "dupack_rate": "Recent duplicate-ACK rate",
    "cwnd_pipe_ratio": "Total cwnd / (BDP + buffer)",
    "cwnd_growth": "cwnd growth over window",
    "throughput_trend": "Goodput trend",
    "utilisation": "Link utilisation",
    "recovery_frac": "Flows in fast recovery",
    "slow_start_frac": "Flows in slow start",
}

DEFAULT_WINDOW_S = 0.2
DEFAULT_HORIZON_S = 0.2
DEFAULT_STRIDE_S = 0.05


def link_series(result: SimulationResult) -> pd.DataFrame:
    """Aggregate the per-flow periodic samples into one row per sample time (cumulative counters)."""
    s = result.samples
    if s.empty:
        return pd.DataFrame()
    g = s.groupby("t")
    out = pd.DataFrame({
        "queue": g["queue"].first(),
        "cwnd_sum": g["cwnd"].sum(),
        "n_flows": g["flow"].count(),
        "recovery": g["phase"].apply(lambda x: float((x == 2).sum())),
        "slow_start": g["phase"].apply(lambda x: float((x == 0).sum())),
        "delivered": g["delivered_segments"].sum(),
        "sent": g["sent_packets"].sum(),
        "retx": g["retx_packets"].sum(),
        "drops": g["drops"].sum(),
        "dupacks": g["dupacks"].sum(),
        "rtt_count": g["rtt_count"].sum(),
        "rtt_sum": g["rtt_sum_ms"].sum(),
        "rtt_sq": g["rtt_sq_sum_ms"].sum(),
        "link_bytes": g["link_bytes_total"].first(),
        "overflow_total": g["overflow_drops_total"].first(),
    })
    return out.reset_index()


def features_from_series(series: pd.DataFrame, cfg: SimulationConfig, window_s: float = DEFAULT_WINDOW_S
                         ) -> pd.DataFrame:
    """Causal features: row i uses only series rows with t <= t_i (and >= t_i - window)."""
    if series.empty:
        return pd.DataFrame(columns=["t"] + FEATURES)
    t = series["t"].to_numpy()
    dt = float(np.median(np.diff(t))) if len(t) > 1 else cfg.sample_interval_s
    k = max(int(round(window_s / dt)), 2)
    half = k // 2

    def lag(col, n):
        a = series[col].to_numpy(dtype=float)
        out = np.full_like(a, np.nan)
        out[n:] = a[:-n]
        return out

    def now(col):
        return series[col].to_numpy(dtype=float)

    buf = float(cfg.buffer_packets)
    pipe = cfg.bdp_packets + buf
    base_rtt_ms = cfg.base_rtt_s * 1000.0
    cap_bytes_per_s = cfg.bandwidth_bps / 8.0
    q = now("queue")
    qmean = pd.Series(q).rolling(k + 1, min_periods=k + 1).mean().to_numpy()
    sent_w = now("sent") - lag("sent", k)
    denom = np.where(sent_w > 0, sent_w, np.nan)
    rc = now("rtt_count") - lag("rtt_count", k)
    rs = now("rtt_sum") - lag("rtt_sum", k)
    rq = now("rtt_sq") - lag("rtt_sq", k)
    with np.errstate(invalid="ignore", divide="ignore"):
        rtt_mean = np.where(rc > 0, rs / rc, np.nan)
        rtt_var = np.where(rc > 1, np.maximum(rq / rc - rtt_mean ** 2, 0.0), np.nan)
    deliv_a = now("delivered") - lag("delivered", half)
    deliv_b = lag("delivered", half) - lag("delivered", k)
    seg_rate_scale = cfg.mss_bytes / (half * dt) / cap_bytes_per_s
    feats = pd.DataFrame({
        "t": t,
        "queue_frac": q / buf,
        "queue_mean_frac": qmean / buf,
        "queue_trend": (q - lag("queue", k)) / buf,
        "rtt_ratio": rtt_mean / base_rtt_ms,
        "rtt_std_ratio": np.sqrt(rtt_var) / base_rtt_ms,
        "loss_recent": (now("drops") - lag("drops", k)) / denom,
        "retx_rate": (now("retx") - lag("retx", k)) / denom,
        "dupack_rate": (now("dupacks") - lag("dupacks", k)) / denom,
        "cwnd_pipe_ratio": now("cwnd_sum") / pipe,
        "cwnd_growth": (now("cwnd_sum") - lag("cwnd_sum", k)) / pipe,
        "throughput_trend": (deliv_a - deliv_b) * seg_rate_scale,
        "utilisation": np.minimum((now("link_bytes") - lag("link_bytes", k)) / (k * dt * cap_bytes_per_s), 1.0),
        "recovery_frac": now("recovery") / now("n_flows"),
        "slow_start_frac": now("slow_start") / now("n_flows"),
    })
    # rows without a full window are dropped by the caller; fill quiet windows sensibly
    feats["rtt_ratio"] = feats["rtt_ratio"].ffill().fillna(1.0)
    feats["rtt_std_ratio"] = feats["rtt_std_ratio"].fillna(0.0)
    for c in ("loss_recent", "retx_rate", "dupack_rate"):
        feats[c] = feats[c].fillna(0.0)
    feats["_complete"] = np.arange(len(t)) >= k
    return feats


def labels_from_series(series: pd.DataFrame, horizon_s: float = DEFAULT_HORIZON_S) -> pd.DataFrame:
    """label = 1 if the cumulative overflow counter increases in (t, t + H]; NaN when t + H is past the end."""
    t = series["t"].to_numpy()
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.01
    h = max(int(round(horizon_s / dt)), 1)
    ov = series["overflow_total"].to_numpy(dtype=float)
    fut = np.full_like(ov, np.nan)
    fut[:-h] = ov[h:]
    lab = np.where(np.isnan(fut), np.nan, (fut - ov > 0).astype(float))
    return pd.DataFrame({"t": t, "label": lab})


def rows_for_run(result: SimulationResult, run_id: str, config_id: str, window_s: float = DEFAULT_WINDOW_S,
                 horizon_s: float = DEFAULT_HORIZON_S, stride_s: float = DEFAULT_STRIDE_S) -> pd.DataFrame:
    series = link_series(result)
    if series.empty:
        return pd.DataFrame()
    feats = features_from_series(series, result.config, window_s)
    labels = labels_from_series(series, horizon_s)
    df = feats.merge(labels, on="t")
    df = df[df["_complete"] & df["label"].notna()].drop(columns="_complete")
    # all flows must have started, so every row describes the same set of senders
    last_start = max(f.start_time_s for f in result.config.flows)
    df = df[df["t"] >= last_start + window_s]
    dt = result.config.sample_interval_s
    step = max(int(round(stride_s / dt)), 1)
    df = df.iloc[::step].copy()
    df["run_id"] = run_id
    df["config_id"] = config_id
    df["algorithms"] = "+".join(result.config.algorithms)
    return df.reset_index(drop=True)


def sample_configs(n: int, rng_seed: int = 0, duration_s: float = 15.0) -> list[tuple[str, SimulationConfig]]:
    """Diverse, valid network configurations for training data."""
    rng = np.random.default_rng(rng_seed)
    out = []
    for i in range(n):
        bw = float(rng.choice([2, 5, 10, 20]))
        delay = float(rng.choice([5, 10, 20, 40]))
        nflows = int(rng.choice([1, 1, 2, 3]))
        algs = [str(rng.choice(D.ALGORITHMS)) for _ in range(nflows)]
        base = make_config(algs, n_flows=nflows, duration_s=duration_s, bandwidth_mbps=bw, delay_ms=delay)
        bdp = max(base.bdp_packets, 1.0)
        buf = int(max(3, round(bdp * float(rng.choice([0.25, 0.5, 1.0, 2.0])))))
        loss = float(rng.choice([0.0, 0.0, 0.001, 0.005, 0.01]))
        ssth = float(rng.choice([32, 64, 256]))
        starts = sorted(float(x) for x in rng.uniform(0, 3, size=nflows))
        starts[0] = 0.0
        cfg = make_config(algs, n_flows=nflows, flow_start_times=starts, duration_s=duration_s, bandwidth_mbps=bw,
                          delay_ms=delay, buffer_packets=buf, loss_prob=loss, initial_ssthresh=ssth,
                          record_packet_events=False, sample_interval_s=0.01)
        out.append((f"C{i:03d}", cfg.ensure_valid()))
    return out


def generate_dataset(n_configs: int = 40, seeds: tuple[int, ...] = (1, 2), duration_s: float = 15.0,
                     rng_seed: int = 0, window_s: float = DEFAULT_WINDOW_S, horizon_s: float = DEFAULT_HORIZON_S,
                     stride_s: float = DEFAULT_STRIDE_S, progress=None) -> pd.DataFrame:
    configs = sample_configs(n_configs, rng_seed, duration_s)
    frames = []
    total = len(configs) * len(seeds)
    i = 0
    for cid, cfg in configs:
        for s in seeds:
            res = run_simulation(replace(cfg, seed=int(s)))
            frames.append(rows_for_run(res, f"{cid}-s{s}", cid, window_s, horizon_s, stride_s))
            i += 1
            if progress:
                progress(i, total)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
