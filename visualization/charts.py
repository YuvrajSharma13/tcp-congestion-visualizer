"""Plotly figures built only from simulation traces."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from config import defaults as D
from simulator.metrics import default_bin_s, throughput_timeseries
from simulator.trace import SimulationResult
from visualization.theme import (ALGO_COLOR, EVENT_SYMBOL, GRID, MUTED, PHASE_FILL, PHASE_LABEL, STATUS, TEMPLATE,
                                 TEXT_2, flow_color)

MAX_POINTS = 6000


def _flow_name(result: SimulationResult, f: int) -> str:
    alg = result.config.flows[f].algorithm
    return f"Flow {f} · {D.ALGORITHM_LABELS[alg]}" if result.config.n_flows > 1 else D.ALGORITHM_LABELS[alg]


def decimate_step(t: np.ndarray, y: np.ndarray, max_points: int = MAX_POINTS) -> tuple[np.ndarray, np.ndarray]:
    """Reduce a step series for display, keeping each bucket's min and max (peaks/troughs survive)."""
    n = len(t)
    if n <= max_points:
        return t, y
    buckets = max_points // 2
    edges = np.linspace(0, n, buckets + 1).astype(int)
    keep = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        seg = y[a:b]
        i1, i2 = a + int(np.argmin(seg)), a + int(np.argmax(seg))
        keep.extend(sorted({i1, i2}))
    keep = np.array(sorted(set(keep) | {0, n - 1}))
    return t[keep], y[keep]


def _base(title: str, ytitle: str, height: int = 340) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(template=TEMPLATE, title=title, height=height, xaxis_title="Simulation time (s)",
                      yaxis_title=ytitle)
    return fig


def phase_intervals(result: SimulationResult, flow: int) -> pd.DataFrame:
    cw = result.cwnd[result.cwnd["flow"] == flow]
    if cw.empty:
        return pd.DataFrame(columns=["start", "end", "phase"])
    ph = cw["phase"].to_numpy()
    t = cw["t"].to_numpy()
    change = np.flatnonzero(ph[1:] != ph[:-1]) + 1
    starts = np.concatenate(([0], change))
    ends = np.concatenate((change, [len(ph)]))
    rows = []
    for s, e in zip(starts, ends):
        rows.append({"start": t[s], "end": t[e] if e < len(t) else result.duration_s, "phase": ph[s]})
    return pd.DataFrame(rows)


def inflation_cap(result: SimulationResult, flows: list[int]) -> float | None:
    """Upper y-limit that hides fast-recovery inflation spikes, or None if they are not dominant."""
    cw = result.cwnd[result.cwnd["flow"].isin(flows)]
    if cw.empty:
        return None
    normal = cw[cw["phase"] != "fast_recovery"]["cwnd"]
    if normal.empty:
        return None
    nmax = float(max(normal.max(), cw["ssthresh"].clip(upper=normal.max() * 2).max()))
    if cw["cwnd"].max() > 1.6 * nmax:
        return nmax * 1.25
    return None


def cwnd_chart(result: SimulationResult, flows: list[int] | None = None, show_ssthresh: bool = True,
               clip_inflation: bool = True, mark_events: bool = True, shade_phases: bool = True,
               height: int = 400) -> tuple[go.Figure, str | None]:
    """cwnd (solid) and ssthresh (dotted) per flow, with phase shading and congestion events.

    Returns (figure, note); note explains any clipping of fast-recovery inflation.
    """
    flows = list(range(result.config.n_flows)) if flows is None else flows
    fig = _base("Congestion window and slow-start threshold", "Segments", height)
    cw = result.cwnd
    for f in flows:
        c = cw[cw["flow"] == f]
        if c.empty:
            continue
        color = flow_color(f) if result.config.n_flows > 1 else ALGO_COLOR[result.config.flows[f].algorithm]
        t, y = decimate_step(c["t"].to_numpy(), c["cwnd"].to_numpy())
        fig.add_trace(go.Scattergl(x=t, y=y, mode="lines", line=dict(color=color, width=2, shape="hv"),
                                   name=f"cwnd · {_flow_name(result, f)}",
                                   hovertemplate="cwnd %{y:.1f}<extra></extra>"))
        if show_ssthresh:
            s = c["ssthresh"].to_numpy()
            ts, ys = decimate_step(c["t"].to_numpy(), np.minimum(s, np.nanmax(c["cwnd"]) * 2))
            fig.add_trace(go.Scattergl(x=ts, y=ys, mode="lines",
                                       line=dict(color=color, width=1.5, dash="dot", shape="hv"),
                                       name=f"ssthresh · {_flow_name(result, f)}", opacity=0.8,
                                       hovertemplate="ssthresh %{y:.1f}<extra></extra>"))
    if shade_phases and len(flows) == 1:
        pi = phase_intervals(result, flows[0])
        shown = set()
        for _, r in pi[pi["phase"] != "congestion_avoidance"].head(400).iterrows():
            fig.add_vrect(x0=r["start"], x1=r["end"], fillcolor=PHASE_FILL[r["phase"]], line_width=0, layer="below")
            shown.add(r["phase"])
        for ph in sorted(shown):  # legend entries for shading
            fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=PHASE_LABEL[ph],
                                     marker=dict(symbol="square", size=12, color=PHASE_FILL[ph].replace("0.1", "0.5")
                                                 .replace("0.14", "0.6"))))
    if mark_events:
        ev = result.events
        for name, label in (("fast_retransmit", "Fast retransmit"), ("timeout", "Timeout"),
                            ("partial_ack", "Partial ACK")):
            e = ev[(ev["event"] == name) & ev["flow"].isin(flows)]
            if e.empty:
                continue
            fig.add_trace(go.Scatter(x=e["t"], y=e["cwnd"], mode="markers", name=label,
                                     marker=dict(symbol=EVENT_SYMBOL[name], size=10, color=STATUS[name],
                                                 line=dict(width=1, color="#0f1115")),
                                     customdata=np.stack([e["flow"], e["seq"]], axis=1),
                                     hovertemplate=f"{label}<br>flow %{{customdata[0]}}, seg %{{customdata[1]}}"
                                                   f"<br>cwnd after %{{y:.1f}}<extra></extra>"))
    note = None
    cap = inflation_cap(result, flows) if clip_inflation else None
    if cap:
        peak = float(cw[cw["flow"].isin(flows)]["cwnd"].max())
        fig.update_yaxes(range=[0, cap])
        note = (f"Fast-recovery window inflation peaks at {peak:,.0f} segments (RFC 5681/6582 add one segment per "
                f"duplicate ACK). The y-axis is clipped at {cap:,.0f}; untick 'Clip inflation' to see it.")
    fig.update_layout(hovermode="closest")
    return fig, note


def ssthresh_chart(result: SimulationResult) -> go.Figure:
    fig = _base("Slow-start threshold", "Segments", 280)
    for f in range(result.config.n_flows):
        c = result.cwnd[result.cwnd["flow"] == f]
        t, y = decimate_step(c["t"].to_numpy(), c["ssthresh"].to_numpy())
        fig.add_trace(go.Scattergl(x=t, y=y, mode="lines", name=_flow_name(result, f),
                                   line=dict(color=flow_color(f), width=2, shape="hv")))
    return fig


def rtt_chart(result: SimulationResult) -> go.Figure:
    fig = _base("Round-trip time per ACK", "RTT (ms)", 300)
    base = result.config.base_rtt_s * 1000
    for f in range(result.config.n_flows):
        r = result.rtt[result.rtt["flow"] == f]
        t, y = decimate_step(r["t"].to_numpy(), r["rtt_ms"].to_numpy())
        fig.add_trace(go.Scattergl(x=t, y=y, mode="lines", name=_flow_name(result, f),
                                   line=dict(color=flow_color(f), width=1.5),
                                   hovertemplate="%{y:.1f} ms<extra></extra>"))
    fig.add_hline(y=base, line=dict(color=MUTED, dash="dash", width=1),
                  annotation_text=f"base RTT {base:.1f} ms", annotation_font_color=TEXT_2)
    return fig


def throughput_chart(result: SimulationResult, bin_s: float | None = None) -> go.Figure:
    bin_s = bin_s or default_bin_s(result)
    ts = throughput_timeseries(result, bin_s)
    fig = _base(f"Goodput ({bin_s * 1000:.0f} ms bins)", "Mbps", 300)
    for f in range(result.config.n_flows):
        s = ts[ts["flow"] == f]
        fig.add_trace(go.Scatter(x=s["t_mid"], y=s["goodput_mbps"], mode="lines", name=_flow_name(result, f),
                                 line=dict(color=flow_color(f), width=2),
                                 hovertemplate="%{y:.2f} Mbps<extra></extra>"))
    if result.config.n_flows > 1:
        agg = ts.groupby("t_mid")["goodput_mbps"].sum(min_count=1)
        fig.add_trace(go.Scatter(x=agg.index, y=agg.values, mode="lines", name="Total",
                                 line=dict(color=TEXT_2, width=1.5, dash="dot")))
    fig.add_hline(y=result.config.bandwidth_mbps, line=dict(color=MUTED, dash="dash", width=1),
                  annotation_text="link capacity", annotation_font_color=TEXT_2)
    return fig


def queue_chart(result: SimulationResult) -> go.Figure:
    fig = _base("Bottleneck queue occupancy", "Packets waiting", 300)
    q = result.queue
    t, y = decimate_step(q["t"].to_numpy(), q["queue"].to_numpy())
    fig.add_trace(go.Scattergl(x=t, y=y, mode="lines", name="Queue", line=dict(color=ALGO_COLOR["newreno"], width=1.5,
                                                                               shape="hv"),
                               hovertemplate="%{y} pkts<extra></extra>"))
    fig.add_hline(y=result.config.buffer_packets, line=dict(color=STATUS["drop"], dash="dash", width=1),
                  annotation_text=f"buffer {result.config.buffer_packets}", annotation_font_color=TEXT_2)
    drops = result.events[(result.events["event"] == "drop") & result.events["info"].str.startswith("overflow")]
    if len(drops):
        fig.add_trace(go.Scatter(x=drops["t"], y=[result.config.buffer_packets] * len(drops), mode="markers",
                                 name="Overflow drop", marker=dict(symbol="x", size=8, color=STATUS["drop"])))
    fig.update_layout(hovermode="closest")
    return fig


def loss_chart(result: SimulationResult) -> go.Figure:
    """Segment number vs time for drops (by cause) and retransmissions (by kind)."""
    fig = _base("Packet losses and retransmissions", "Segment number", 320)
    ev = result.events
    d = ev[ev["event"] == "drop"]
    cause = d["info"].str.split(":").str[0]
    sym = {"overflow": "x", "random": "x-thin-open", "burst": "square-x-open", "forced": "star"}
    for c in ["overflow", "random", "burst", "forced"]:
        s = d[cause == c]
        if len(s):
            fig.add_trace(go.Scattergl(x=s["t"], y=s["seq"], mode="markers", name=f"Drop · {c}",
                                       marker=dict(symbol=sym[c], size=8, color=STATUS["drop"],
                                                   line=dict(width=1.5, color=STATUS["drop"])),
                                       hovertemplate=f"{c} drop<br>flow %{{text}}, seg %{{y}}<extra></extra>",
                                       text=s["flow"]))
    r = ev[(ev["event"] == "send") & (ev["info"] != "new")]
    kinds = {"fast_retx": "Fast retransmit", "partial_retx": "Partial-ACK retransmit",
             "rto_retx": "Timeout retransmit", "gbn_retx": "Go-back-N resend"}
    colors = {"fast_retx": STATUS["fast_retransmit"], "partial_retx": STATUS["partial_ack"],
              "rto_retx": STATUS["timeout"], "gbn_retx": MUTED}
    for k, lab in kinds.items():
        s = r[r["info"] == k]
        if len(s):
            fig.add_trace(go.Scattergl(x=s["t"], y=s["seq"], mode="markers", name=lab,
                                       marker=dict(symbol="circle", size=6, color=colors[k]),
                                       text=s["flow"], hovertemplate=f"{lab}<br>flow %{{text}}, seg %{{y}}<extra></extra>"))
    fig.update_layout(hovermode="closest")
    return fig


TIMELINE_EVENTS = ["flow_start", "phase_change", "drop", "fast_retransmit", "enter_recovery", "partial_ack",
                   "exit_recovery", "timeout"]


def event_timeline(result: SimulationResult) -> go.Figure:
    ev = result.events[result.events["event"].isin(TIMELINE_EVENTS)]
    fig = _base("Event timeline", "", 320)
    colors = {"drop": STATUS["drop"], "timeout": STATUS["timeout"], "fast_retransmit": STATUS["fast_retransmit"],
              "partial_ack": STATUS["partial_ack"]}
    for name in TIMELINE_EVENTS:
        s = ev[ev["event"] == name]
        if s.empty:
            continue
        if len(s) > MAX_POINTS:
            s = s.iloc[:: math.ceil(len(s) / MAX_POINTS)]
        fig.add_trace(go.Scattergl(
            x=s["t"], y=[name.replace("_", " ")] * len(s), mode="markers", name=name.replace("_", " "),
            marker=dict(size=8, symbol=EVENT_SYMBOL.get(name, "line-ns-open"), color=colors.get(name, TEXT_2),
                        line=dict(width=1.5, color=colors.get(name, TEXT_2))),
            customdata=np.stack([s["flow"], s["seq"], s["info"]], axis=1),
            hovertemplate="t=%{x:.4f}s · flow %{customdata[0]} · seg %{customdata[1]}<br>%{customdata[2]}<extra></extra>"))
    fig.update_layout(showlegend=False, hovermode="closest")
    fig.update_yaxes(rangemode="normal", gridcolor=GRID)
    return fig


# ------------------------------------------------------------- comparison
def overlay_cwnd(runs, clip: bool = True) -> go.Figure:
    fig = _base("Congestion window, same network and seed", "Segments (flow 0)", 420)
    cap = 0.0
    for r in runs:
        c = r.result.cwnd[r.result.cwnd["flow"] == 0]
        t, y = decimate_step(c["t"].to_numpy(), c["cwnd"].to_numpy())
        fig.add_trace(go.Scattergl(x=t, y=y, mode="lines", name=D.ALGORITHM_LABELS[r.algorithm],
                                   line=dict(color=ALGO_COLOR[r.algorithm], width=2, shape="hv")))
        cp = inflation_cap(r.result, [0])
        cap = max(cap, cp or float(c["cwnd"].max() * 1.05))
    if clip and cap:
        fig.update_yaxes(range=[0, cap])
    return fig


def metric_bars(table: pd.DataFrame, metric: str, title: str, unit: str) -> go.Figure:
    fig = _base(title, unit, 260)
    fig.add_trace(go.Bar(x=[D.ALGORITHM_LABELS[a] for a in table["algorithm"]], y=table[metric],
                         marker=dict(color=[ALGO_COLOR[a] for a in table["algorithm"]], cornerradius=4),
                         text=[f"{v:.2f}" if isinstance(v, float) and not math.isnan(v) else str(v)
                               for v in table[metric]], textposition="outside",
                         hovertemplate="%{x}: %{y:.3f}<extra></extra>"))
    fig.update_layout(showlegend=False, hovermode="closest", xaxis_title="", bargap=0.45)
    return fig


def per_flow_bars(metrics, title: str = "Per-flow goodput") -> go.Figure:
    fig = _base(title, "Mbps", 260)
    fig.add_trace(go.Bar(x=[f"Flow {f.flow} · {D.ALGORITHM_LABELS[f.algorithm]}" for f in metrics.flows],
                         y=[f.goodput_mbps for f in metrics.flows],
                         marker=dict(color=[flow_color(f.flow) for f in metrics.flows], cornerradius=4),
                         text=[f"{f.goodput_mbps:.2f}" for f in metrics.flows], textposition="outside"))
    fig.update_layout(showlegend=False, hovermode="closest", xaxis_title="", bargap=0.45)
    return fig


def jain_chart(fo: pd.DataFrame) -> go.Figure:
    fig = _base("Jain's fairness index over time", "J", 260)
    fig.add_trace(go.Scatter(x=fo["t_mid"], y=fo["jain"], mode="lines", line=dict(color=ALGO_COLOR["newreno"], width=2),
                             name="Jain"))
    fig.update_yaxes(range=[0, 1.05])
    fig.update_layout(showlegend=False)
    return fig


def sensitivity_chart(summary: pd.DataFrame, param_label: str, response_label: str) -> go.Figure:
    fig = _base(f"{response_label} vs {param_label}", response_label, 380)
    fig.update_layout(xaxis_title=param_label, hovermode="closest")
    for alg, s in summary.groupby("algorithm", sort=False):
        err = s["ci95"].fillna(0)
        fig.add_trace(go.Scatter(x=s["value"], y=s["mean"], mode="lines+markers", name=D.ALGORITHM_LABELS[alg],
                                 line=dict(color=ALGO_COLOR[alg], width=2), marker=dict(size=8),
                                 error_y=dict(type="data", array=err, visible=True, thickness=1.2, width=4),
                                 customdata=np.stack([s["std"], s["count"], s["min"], s["max"]], axis=1),
                                 hovertemplate="%{x}: mean %{y:.3f} ± %{error_y.array:.3f} (95% CI)<br>"
                                               "sd %{customdata[0]:.3f}, n=%{customdata[1]}, "
                                               "range %{customdata[2]:.3f}–%{customdata[3]:.3f}<extra></extra>"))
    return fig


def risk_chart(times: np.ndarray, probs: np.ndarray, actual: np.ndarray, horizon_s: float) -> go.Figure:
    fig = _base(f"Predicted probability of buffer overflow in the next {horizon_s * 1000:.0f} ms",
                "Probability", 300)
    fig.add_trace(go.Scatter(x=times, y=probs, mode="lines", name="Predicted risk",
                             line=dict(color=ALGO_COLOR["tahoe"], width=2)))
    hit = times[actual.astype(bool)]
    fig.add_trace(go.Scatter(x=hit, y=[1.02] * len(hit), mode="markers", name="Overflow actually followed",
                             marker=dict(symbol="line-ns-open", size=10, color=STATUS["drop"])))
    for y0, y1, c in ((0, 0.3, "rgba(63,191,127,0.06)"), (0.3, 0.6, "rgba(255,176,32,0.06)"),
                      (0.6, 1.0, "rgba(255,92,92,0.07)")):
        fig.add_hrect(y0=y0, y1=y1, fillcolor=c, line_width=0, layer="below")
    fig.update_yaxes(range=[0, 1.06])
    return fig
