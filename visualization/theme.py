"""Shared visual identity: colours, Plotly template, labels.

Categorical colours follow a fixed order (never cycled) taken from a palette
validated for colour-vision deficiency on a dark surface.  Algorithms always
use the same colour; flows in a multi-flow run use slots in flow order.
Status colours (drops, timeouts) are reserved and never used for series.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

SURFACE = "#0f1115"
SURFACE_2 = "#161a21"
GRID = "#262b35"
TEXT = "#e8e9ec"
TEXT_2 = "#a7adb9"
MUTED = "#6f7684"
ACCENT = "#3987e5"

SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
ALGO_COLOR = {"tahoe": SERIES[0], "reno": SERIES[1], "newreno": SERIES[2], "cubic": SERIES[3]}

# reserved status colours (with symbols, never colour alone)
STATUS = {
    "drop": "#ff5c5c",
    "timeout": "#ffb020",
    "fast_retransmit": "#f2f2f2",
    "partial_ack": "#7fd1ff",
    "good": "#3fbf7f",
}
EVENT_SYMBOL = {"drop": "x", "timeout": "diamond", "fast_retransmit": "triangle-down", "partial_ack": "circle-open"}

PHASE_FILL = {
    "slow_start": "rgba(57,135,229,0.10)",
    "congestion_avoidance": "rgba(0,0,0,0)",
    "fast_recovery": "rgba(213,81,129,0.14)",
}
PHASE_LABEL = {"slow_start": "Slow start", "congestion_avoidance": "Congestion avoidance",
               "fast_recovery": "Fast recovery"}

FONT = "Inter, 'Segoe UI', system-ui, -apple-system, sans-serif"

_template = go.layout.Template(
    layout=dict(
        font=dict(family=FONT, color=TEXT, size=13),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        colorway=SERIES,
        margin=dict(l=56, r=20, t=84, b=44),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=SURFACE_2, bordercolor=GRID, font=dict(color=TEXT, family=FONT)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT_2)),
        title=dict(font=dict(size=15, color=TEXT), x=0, xanchor="left", y=0.985, yanchor="top"),
        xaxis=dict(gridcolor=GRID, zeroline=False, linecolor=GRID, tickcolor=GRID, color=TEXT_2),
        yaxis=dict(gridcolor=GRID, zeroline=False, linecolor=GRID, tickcolor=GRID, color=TEXT_2, rangemode="tozero"),
    )
)
pio.templates["tcpviz"] = _template
TEMPLATE = "tcpviz"


def flow_color(flow: int) -> str:
    return SERIES[flow % len(SERIES)] if flow >= 0 else MUTED
