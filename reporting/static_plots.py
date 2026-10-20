"""Publication-style static figures (PNG/SVG) with Matplotlib.

Plotly's own PNG export needs a Chrome installation (kaleido); Matplotlib works
offline on any laptop, so static exports use it.  Interactive charts in the
dashboard can still be saved with the camera icon in each chart's toolbar.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from config import defaults as D  # noqa: E402
from simulator.metrics import throughput_timeseries  # noqa: E402
from simulator.trace import SimulationResult  # noqa: E402

# light-surface steps of the same categorical palette used in the dashboard
LIGHT_SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
ALGO = {"tahoe": LIGHT_SERIES[0], "reno": LIGHT_SERIES[1], "newreno": LIGHT_SERIES[2], "cubic": LIGHT_SERIES[3]}

STYLE = {
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": "#e3e3e0", "grid.linewidth": 0.6,
    "legend.frameon": False, "figure.dpi": 150, "savefig.bbox": "tight", "lines.linewidth": 1.4,
}

FIGURES = ("cwnd", "throughput", "rtt", "queue")


def _color(result, f):
    return LIGHT_SERIES[f % 8] if result.config.n_flows > 1 else ALGO[result.config.flows[f].algorithm]


def figure(result: SimulationResult, kind: str, clip_inflation: bool = True):
    if kind not in FIGURES:
        raise ValueError(f"Unknown figure {kind!r}; choose from {FIGURES}")
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(6.4, 3.0))
        cfg = result.config
        names = [f"Flow {i} ({D.ALGORITHM_LABELS[f.algorithm]})" if cfg.n_flows > 1 else D.ALGORITHM_LABELS[f.algorithm]
                 for i, f in enumerate(cfg.flows)]
        if kind == "cwnd":
            ymax = 0.0
            for f in range(cfg.n_flows):
                c = result.cwnd[result.cwnd["flow"] == f]
                ax.step(c["t"], c["cwnd"], where="post", color=_color(result, f), label=f"cwnd, {names[f]}")
                ax.step(c["t"], c["ssthresh"].clip(upper=c["cwnd"].max() * 2), where="post", color=_color(result, f),
                        linestyle=":", linewidth=1, label=f"ssthresh, {names[f]}")
                normal = c[c["phase"] != "fast_recovery"]["cwnd"]
                ymax = max(ymax, normal.max() if len(normal) else c["cwnd"].max())
            if clip_inflation and result.cwnd["cwnd"].max() > 1.6 * ymax:
                ax.set_ylim(0, ymax * 1.25)
            ax.set_ylabel("segments")
            ax.set_title("Congestion window")
        elif kind == "throughput":
            ts = throughput_timeseries(result)
            for f in range(cfg.n_flows):
                s = ts[ts["flow"] == f]
                ax.plot(s["t_mid"], s["goodput_mbps"], color=_color(result, f), label=names[f])
            ax.axhline(cfg.bandwidth_mbps, color="#8a8a86", linestyle="--", linewidth=0.8, label="capacity")
            ax.set_ylabel("goodput (Mbps)")
            ax.set_title("Goodput")
        elif kind == "rtt":
            for f in range(cfg.n_flows):
                r = result.rtt[result.rtt["flow"] == f]
                ax.plot(r["t"], r["rtt_ms"], color=_color(result, f), linewidth=0.9, label=names[f])
            ax.axhline(cfg.base_rtt_s * 1000, color="#8a8a86", linestyle="--", linewidth=0.8, label="base RTT")
            ax.set_ylabel("RTT (ms)")
            ax.set_title("Round-trip time")
        else:
            q = result.queue
            ax.step(q["t"], q["queue"], where="post", color=LIGHT_SERIES[2], label="queue")
            ax.axhline(cfg.buffer_packets, color=LIGHT_SERIES[7], linestyle="--", linewidth=0.8, label="buffer")
            ax.set_ylabel("packets waiting")
            ax.set_title("Bottleneck queue")
        ax.set_xlabel("simulation time (s)")
        ax.set_xlim(0, result.duration_s)
        ax.set_ylim(bottom=0)
        if len(ax.get_legend_handles_labels()[0]) > 1:
            ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=8)
        return fig


def render(result: SimulationResult, kind: str, fmt: str = "png") -> bytes:
    if fmt not in ("png", "svg"):
        raise ValueError("format must be 'png' or 'svg'")
    fig = figure(result, kind)
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


_ = np
