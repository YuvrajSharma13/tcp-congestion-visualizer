"""Dumbbell topology diagram, optionally populated with packets from a playback state."""

from __future__ import annotations

import plotly.graph_objects as go

from config import defaults as D
from visualization.theme import GRID, MUTED, STATUS, SURFACE, SURFACE_2, TEMPLATE, TEXT, TEXT_2, flow_color

ROUTER_X = 4.2
RX_X = 10.0
LINK_Y = 0.0
ACK_Y = -1.6
SLOTS_MAX = 24
SLOT_X0, SLOT_X1 = 1.6, 3.9


def _box(fig, x0, y0, x1, y1, color=SURFACE_2, line=GRID):
    fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1, fillcolor=color, line=dict(color=line, width=1.5),
                  layer="below")


def topology_figure(cfg, state: dict | None = None, height: int = 360) -> go.Figure:
    n = cfg.n_flows
    fig = go.Figure()
    fig.update_layout(template=TEMPLATE, height=height, showlegend=False, hovermode="closest",
                      margin=dict(l=10, r=10, t=10, b=10))
    fig.update_xaxes(visible=False, range=[-0.6, 11.4])
    fig.update_yaxes(visible=False, range=[-2.2, max(0.9, 0.25 * n + 0.75)])

    ys = [0.5 * (i - (n - 1) / 2) for i in range(n)]
    for i, y in enumerate(ys):
        _box(fig, -0.4, y - 0.18, 0.9, y + 0.18, line=flow_color(i))
        fig.add_annotation(x=0.25, y=y, text=f"S{i} · {D.ALGORITHM_LABELS[cfg.flows[i].algorithm].split()[-1]}",
                           showarrow=False, font=dict(size=11, color=TEXT))
        fig.add_shape(type="line", x0=0.9, y0=y, x1=SLOT_X0 - 0.05, y1=LINK_Y, line=dict(color=GRID, width=1.5))
    # buffer
    _box(fig, SLOT_X0, -0.28, SLOT_X1, 0.28)
    slots = min(cfg.buffer_packets, SLOTS_MAX)
    w = (SLOT_X1 - SLOT_X0) / slots
    for k in range(slots + 1):
        fig.add_shape(type="line", x0=SLOT_X0 + k * w, x1=SLOT_X0 + k * w, y0=-0.28, y1=0.28,
                      line=dict(color=GRID, width=1))
    fig.add_annotation(x=(SLOT_X0 + SLOT_X1) / 2, y=0.55, showarrow=False,
                       text=f"FIFO drop-tail buffer · {cfg.buffer_packets} pkts", font=dict(size=11, color=TEXT_2))
    # router + link + receiver
    fig.add_shape(type="circle", x0=ROUTER_X - 0.3, y0=-0.3, x1=ROUTER_X + 0.3, y1=0.3, fillcolor=SURFACE_2,
                  line=dict(color=TEXT_2, width=1.5))
    fig.add_annotation(x=ROUTER_X, y=-0.55, text="router", showarrow=False, font=dict(size=11, color=TEXT_2))
    fig.add_shape(type="line", x0=ROUTER_X + 0.3, y0=LINK_Y, x1=RX_X - 0.6, y1=LINK_Y,
                  line=dict(color=TEXT_2, width=3))
    fig.add_annotation(x=(ROUTER_X + RX_X) / 2, y=0.42, showarrow=False, font=dict(size=11, color=TEXT_2),
                       text=f"bottleneck {cfg.bandwidth_mbps:g} Mbps · {cfg.delay_ms:g} ms one way"
                            + (f" · loss {cfg.loss_prob * 100:g}%" if cfg.loss_prob else ""))
    _box(fig, RX_X - 0.6, -0.3, RX_X + 0.9, 0.3, line=TEXT_2)
    fig.add_annotation(x=RX_X + 0.15, y=0, text="Receiver(s)", showarrow=False, font=dict(size=11, color=TEXT))
    # ACK path
    fig.add_shape(type="line", x0=RX_X + 0.15, y0=-0.3, x1=RX_X + 0.15, y1=ACK_Y, line=dict(color=GRID, width=1.5))
    fig.add_shape(type="line", x0=RX_X + 0.15, y0=ACK_Y, x1=0.25, y1=ACK_Y, line=dict(color=GRID, width=1.5, dash="dot"))
    fig.add_shape(type="line", x0=0.25, y0=ACK_Y, x1=0.25, y1=min(ys) - 0.18, line=dict(color=GRID, width=1.5,
                                                                                      dash="dot"))
    fig.add_annotation(x=(RX_X + 0.25) / 2, y=ACK_Y - 0.35, showarrow=False, font=dict(size=11, color=TEXT_2),
                       text=f"◀ cumulative ACKs return ({cfg.delay_ms:g} ms, never lost)")
    if cfg.cross_traffic.enabled:
        fig.add_annotation(x=1.0, y=-0.8, text=f"+ cross traffic {cfg.cross_traffic.rate_mbps:g} Mbps",
                           showarrow=False, font=dict(size=10, color=MUTED))
    if state is not None:
        _draw_state(fig, cfg, state)
    return fig


def _draw_state(fig, cfg, s):
    q = s["queued"]
    slots = min(cfg.buffer_packets, SLOTS_MAX)
    w = (SLOT_X1 - SLOT_X0) / slots
    nq = len(q)
    if cfg.buffer_packets <= SLOTS_MAX:
        for k, (_, p) in enumerate(q.iterrows()):
            x0 = SLOT_X1 - (k + 1) * w
            fig.add_shape(type="rect", x0=x0 + 0.01, x1=x0 + w - 0.01, y0=-0.24, y1=0.24,
                          fillcolor=flow_color(int(p["flow"])), line_width=0)
    else:
        frac = nq / cfg.buffer_packets
        fig.add_shape(type="rect", x0=SLOT_X1 - frac * (SLOT_X1 - SLOT_X0), x1=SLOT_X1, y0=-0.24, y1=0.24,
                      fillcolor=STATUS["partial_ack"], opacity=0.7, line_width=0)
    fig.add_annotation(x=(SLOT_X0 + SLOT_X1) / 2, y=-0.5, showarrow=False, font=dict(size=12, color=TEXT),
                       text=f"queue {nq}/{cfg.buffer_packets}")
    xs, ys, cs, txt, sym = [], [], [], [], []
    for _, p in s["service"].iterrows():
        xs.append(ROUTER_X); ys.append(0); cs.append(flow_color(int(p["flow"])))
        txt.append(f"serialising: flow {p['flow']} seg {p['seq']}"); sym.append("square")
    for _, p in s["fly"].iterrows():
        xs.append(ROUTER_X + 0.3 + p["pos"] * (RX_X - 0.9 - ROUTER_X)); ys.append(0)
        cs.append(flow_color(int(p["flow"])))
        retx = p["kind"] not in ("new", "cross")
        txt.append(f"data flow {p['flow']} seg {p['seq']}" + (" (retransmission)" if retx else ""))
        sym.append("square-open" if retx else "square")
    if xs:
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers", text=txt, hovertemplate="%{text}<extra></extra>",
                                 marker=dict(size=13, color=cs, symbol=sym, line=dict(width=2, color=cs))))
    a = s["acks"]
    if len(a):
        fig.add_trace(go.Scatter(x=RX_X + 0.15 - a["pos"] * (RX_X - 0.1), y=[ACK_Y] * len(a), mode="markers",
                                 marker=dict(size=9, symbol="triangle-left", color=[flow_color(int(f)) for f in a["flow"]]),
                                 text=[f"ACK {int(x)} (flow {f})" for x, f in zip(a["ack"], a["flow"])],
                                 hovertemplate="%{text}<extra></extra>"))
    d = s["drops"]
    if len(d):
        dx = [SLOT_X0 - 0.25 if c == "overflow" else (ROUTER_X + RX_X) / 2 for c in d["drop_cause"]]
        fig.add_trace(go.Scatter(x=dx, y=[0.0] * len(d), mode="markers+text",
                                 marker=dict(symbol="x", size=16, color=STATUS["drop"]),
                                 text=["drop"] * len(d), textposition="bottom center",
                                 textfont=dict(color=STATUS["drop"], size=11),
                                 hovertext=[f"{c} drop: flow {f} seg {q}" for c, f, q in
                                            zip(d["drop_cause"], d["flow"], d["seq"])],
                                 hovertemplate="%{hovertext}<extra></extra>"))
    _ = SURFACE
