"""Import and summarise real Linux TCP traces captured with ``ss -tin``.

Expected input (written by ``tools/capture_ss_trace.sh``)::

    # t=1792347591.810933980          <- sample timestamp, Unix seconds
    State Recv-Q Send-Q Local Address:Port Peer Address:Port
    ESTAB 0 76744 127.0.0.1:51328 127.0.0.1:5201
        reno wscale:10,10 rto:204 rtt:0.692/1.193 mss:1448 ... cwnd:13 ssthresh:29 ... bytes_acked:2934 ...

Units and semantics (Linux ``ss`` output):
* ``cwnd`` and ``ssthresh`` are in **segments** of ``mss`` bytes - the same unit
  as the simulator.  ``ssthresh`` is absent until the first reduction.
* ``rtt:<srtt>/<rttvar>`` are in **milliseconds** (kernel smoothed estimates,
  not per-ACK samples).
* Sampling frequency is whatever the capture loop used (e.g. every 50 ms), so
  events shorter than one interval - such as fast-recovery inflation - are
  usually invisible.

Limitations: the kernel's cwnd is that of Linux's own implementation (SACK,
PRR, HyStart++, pacing, TSO autosizing, delayed ACKs), so only the *shape*
and summary statistics are comparable with the simulator.  Nothing here
modifies the operating system.
"""

from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

from simulator.trace import SimulationResult

_TS = re.compile(r"^#\s*t=([0-9.]+)")
_CONN = re.compile(r"^(ESTAB|SYN-SENT|FIN-WAIT-\d|CLOSE-WAIT|LAST-ACK|TIME-WAIT)\s+\d+\s+\d+\s+(\S+)\s+(\S+)")
_FIELDS = {
    "cwnd": re.compile(r"(?<![\w_])cwnd:(\d+)"),
    "ssthresh": re.compile(r"(?<![\w_])ssthresh:(\d+)"),
    "mss": re.compile(r"(?<![\w_])mss:(\d+)"),
    "bytes_acked": re.compile(r"bytes_acked:(\d+)"),
    "rto_ms": re.compile(r"(?<![\w_])rto:([\d.]+)"),
}
_RTT = re.compile(r"(?<![\w_])rtt:([\d.]+)/([\d.]+)")
_RETRANS = re.compile(r"retrans:(\d+)/(\d+)")
_RATE = re.compile(r"delivery_rate (\d+(?:\.\d+)?)([KMG]?)bps")
_ALGS = ("reno", "cubic", "bbr", "bbr2", "vegas", "westwood", "htcp", "dctcp")


class TraceFormatError(ValueError):
    pass


def parse_ss_trace(text: str) -> pd.DataFrame:
    rows = []
    t = None
    conn = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _TS.match(line)
        if m:
            t = float(m.group(1))
            continue
        m = _CONN.match(line)
        if m:
            conn = f"{m.group(2)}->{m.group(3)}"
            continue
        if t is None or conn is None or "cwnd:" not in line:
            continue
        first = line.split()[0]
        row = {"t_abs": t, "conn": conn, "algorithm": first if first in _ALGS else "unknown"}
        for k, rx in _FIELDS.items():
            mm = rx.search(line)
            row[k] = float(mm.group(1)) if mm else math.nan
        mm = _RTT.search(line)
        row["rtt_ms"], row["rttvar_ms"] = (float(mm.group(1)), float(mm.group(2))) if mm else (math.nan, math.nan)
        mm = _RETRANS.search(line)
        row["retrans_total"] = float(mm.group(2)) if mm else 0.0
        mm = _RATE.search(line)
        if mm:
            mult = {"": 1, "K": 1e3, "M": 1e6, "G": 1e9}[mm.group(2)]
            row["delivery_rate_mbps"] = float(mm.group(1)) * mult / 1e6
        else:
            row["delivery_rate_mbps"] = math.nan
        rows.append(row)
        conn = None
    if not rows:
        raise TraceFormatError("No 'ss -tin' samples with a cwnd field were found. Expected lines starting with "
                               "'# t=<unix seconds>' followed by ss output (see tools/capture_ss_trace.sh).")
    df = pd.DataFrame(rows)
    df["t"] = df["t_abs"] - df["t_abs"].min()
    return df


def main_connection(df: pd.DataFrame) -> pd.DataFrame:
    """The connection that moved the most data (ignores e.g. iperf3's control connection)."""
    best = df.groupby("conn")["bytes_acked"].max().idxmax()
    return df[df["conn"] == best].sort_values("t").reset_index(drop=True)


def _reductions(t: np.ndarray, cwnd: np.ndarray, threshold: float = 0.2) -> list[float]:
    out = []
    for i in range(1, len(cwnd)):
        if cwnd[i - 1] > 0 and (cwnd[i - 1] - cwnd[i]) / cwnd[i - 1] >= threshold:
            out.append(float(t[i]))
    return out


def summarize_curve(t: np.ndarray, cwnd: np.ndarray, rtt_ms: np.ndarray | None, skip_s: float = 1.0) -> dict:
    mask = t >= skip_s
    if mask.sum() < 3:
        mask = np.ones_like(t, dtype=bool)
    c = cwnd[mask]
    red = _reductions(t[mask], c)
    return {
        "samples": int(mask.sum()),
        "mean_cwnd": float(np.mean(c)),
        "cwnd_cv": float(np.std(c) / np.mean(c)) if np.mean(c) > 0 else math.nan,
        "peak_cwnd": float(np.max(c)),
        "trough_cwnd": float(np.min(c)),
        "trough_to_peak": float(np.min(c) / np.max(c)) if np.max(c) > 0 else math.nan,
        "reductions_per_10s": len(red) / max(t[mask][-1] - t[mask][0], 1e-9) * 10,
        "mean_rtt_ms": float(np.nanmean(rtt_ms[mask])) if rtt_ms is not None and np.isfinite(rtt_ms[mask]).any()
        else math.nan,
    }


def sample_simulation(result: SimulationResult, interval_s: float, flow: int = 0) -> pd.DataFrame:
    """Sample the simulated cwnd like ``ss`` would: the value in force every ``interval_s`` seconds."""
    cw = result.cwnd[result.cwnd["flow"] == flow]
    ts = np.arange(0.0, result.duration_s, interval_s)
    idx = np.searchsorted(cw["t"].to_numpy(), ts, side="right") - 1
    idx = np.clip(idx, 0, len(cw) - 1)
    out = pd.DataFrame({"t": ts, "cwnd": cw["cwnd"].to_numpy()[idx], "phase": cw["phase"].to_numpy()[idx]})
    s = result.samples[result.samples["flow"] == flow]
    if len(s):
        j = np.clip(np.searchsorted(s["t"].to_numpy(), ts, side="right") - 1, 0, len(s) - 1)
        out["rtt_ms"] = s["srtt_ms"].to_numpy()[j]
    else:
        out["rtt_ms"] = math.nan
    return out


def compare(real: pd.DataFrame, result: SimulationResult, flow: int = 0) -> pd.DataFrame:
    interval = float(np.median(np.diff(real["t"]))) if len(real) > 1 else 0.05
    sim = sample_simulation(result, interval, flow)
    a = summarize_curve(real["t"].to_numpy(), real["cwnd"].to_numpy(), real["rtt_ms"].to_numpy())
    b = summarize_curve(sim["t"].to_numpy(), sim["cwnd"].to_numpy(), sim["rtt_ms"].to_numpy())
    rows = [{"statistic": k, "real (ss -ti)": a[k], "simulated": b[k]} for k in a]
    return pd.DataFrame(rows)
