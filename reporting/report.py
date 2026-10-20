"""Self-contained HTML experiment report generated from real simulation data.

The report embeds plotly.js once (so it opens offline), the configuration, the
headline and per-flow metrics, the interactive charts, the congestion events
with their rule-based explanations, and the trace-audit results.
"""

from __future__ import annotations

import datetime as _dt
import html
import math

import pandas as pd

from analytics.explain import explain_event
from config import defaults as D
from simulator.metrics import RunMetrics, flow_metrics_frame
from simulator.trace import SimulationResult
from validation.rfc_checks import audit_trace
from visualization import charts


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    if isinstance(v, float):
        return f"{v:,.3f}" if abs(v) < 100 else f"{v:,.1f}"
    return html.escape(str(v))


def _table(df: pd.DataFrame) -> str:
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    body = "".join("<tr>" + "".join(f"<td>{_fmt(v)}</td>" for v in row) + "</tr>" for row in df.itertuples(index=False))
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


CSS = """
:root{--bg:#0f1115;--s2:#161a21;--line:#262b35;--t:#e8e9ec;--t2:#a7adb9;--acc:#3987e5}
@media (prefers-color-scheme: light){:root{--bg:#fbfbfa;--s2:#f1f1ee;--line:#dddcd6;--t:#16161a;--t2:#55555c}}
body{background:var(--bg);color:var(--t);font-family:Inter,'Segoe UI',system-ui,sans-serif;margin:0;padding:24px;
max-width:1180px;margin:auto;line-height:1.5}
h1{font-size:24px;margin:0 0 4px} h2{font-size:17px;margin:32px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
.sub{color:var(--t2);font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:16px}
.kpi{background:var(--s2);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.kpi b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.kpi span{color:var(--t2);font-size:12px}
table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums;margin:6px 0}
th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{color:var(--t2);font-weight:600}.pass{color:#3fbf7f}.fail{color:#ff5c5c}
.note{color:var(--t2);font-size:12.5px}
"""


def build_report(result: SimulationResult, metrics: RunMetrics, run_id: str = "", title: str = "") -> str:
    cfg = result.config
    when = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    title = title or "TCP Congestion Control Experiment"
    kpis = [
        ("Goodput", f"{metrics.aggregate_goodput_mbps:.2f} Mbps"),
        ("Link utilisation", f"{metrics.link_utilisation_pct:.1f} %"),
        ("Packet loss", f"{metrics.loss_pct:.2f} %"),
        ("Average RTT", _fmt(metrics.avg_rtt_ms) + " ms"),
        ("Fast retransmits", str(metrics.fast_retransmits)),
        ("Timeouts", str(metrics.timeouts)),
        ("Jain's index", _fmt(metrics.jain_index)),
    ]
    kpi_html = "".join(f"<div class='kpi'><span>{k}</span><b>{v}</b></div>" for k, v in kpis)

    cfg_rows = pd.DataFrame([
        ("Algorithms (per flow)", ", ".join(D.ALGORITHM_LABELS[a] for a in cfg.algorithms)),
        ("Flow start times (s)", ", ".join(f"{f.start_time_s:g}" for f in cfg.flows)),
        ("Bottleneck bandwidth", f"{cfg.bandwidth_mbps:g} Mbps"),
        ("One-way propagation delay", f"{cfg.delay_ms:g} ms (base RTT {cfg.base_rtt_s * 1000:.2f} ms)"),
        ("MSS / packet size", f"{cfg.mss_bytes} bytes"),
        ("Buffer", f"{cfg.buffer_packets} packets ({cfg.buffer_packets / cfg.bdp_packets:.2f} × BDP)"
         if cfg.bdp_packets else f"{cfg.buffer_packets} packets"),
        ("BDP", f"{cfg.bdp_packets:.1f} packets"),
        ("Random loss (data packets only)", f"{cfg.loss_prob:g}"),
        ("Loss bursts / forced drops", f"{len(cfg.loss_bursts)} / {len(cfg.forced_drops)}"),
        ("Duration", f"{cfg.duration_s:g} s"),
        ("Seed", str(cfg.seed)),
        ("Initial cwnd / ssthresh", f"{cfg.flows[0].initial_cwnd:g} / {cfg.flows[0].initial_ssthresh:g} segments"),
        ("RTO min / initial / max", f"{cfg.min_rto_s:g} / {cfg.initial_rto_s:g} / {cfg.max_rto_s:g} s"),
        ("NewReno timer variant", cfg.newreno_timer_variant),
        ("Cross traffic", f"{cfg.cross_traffic.rate_mbps:g} Mbps {cfg.cross_traffic.pattern}"
         if cfg.cross_traffic.enabled else "none"),
        ("Simulator version", D.SIMULATOR_VERSION),
    ], columns=["Parameter", "Value"])

    figs = []
    fig, note = charts.cwnd_chart(result)
    figs.append((fig, note))
    for f in (charts.throughput_chart(result), charts.rtt_chart(result), charts.queue_chart(result),
              charts.loss_chart(result)):
        figs.append((f, None))
    chart_html = []
    for i, (f, n) in enumerate(figs):
        chart_html.append(f.to_html(full_html=False, include_plotlyjs=(i == 0), config={"displaylogo": False}))
        if n:
            chart_html.append(f"<p class='note'>{html.escape(n)}</p>")

    pf = flow_metrics_frame(metrics)[["flow", "algorithm", "goodput_mbps", "sent_packets", "retx_packets", "drops",
                                      "loss_pct", "fast_retransmits", "timeouts", "avg_rtt_ms", "avg_cwnd",
                                      "peak_cwnd"]]
    ev = result.events[result.events["event"].isin(["fast_retransmit", "partial_ack", "timeout", "exit_recovery"])]
    shown = ev.head(40)
    ev_rows = "".join(
        f"<tr><td>{r['t']:.4f}</td><td>{html.escape(r['event'])}</td><td>{int(r['flow'])}</td>"
        f"<td>{html.escape(explain_event(result, r))}</td></tr>" for _, r in shown.iterrows())
    more = f"<p class='note'>Showing the first {len(shown)} of {len(ev)} congestion events.</p>" if len(ev) > 40 else ""
    audit = audit_trace(result)
    audit_rows = "".join(f"<tr><td>{html.escape(a.check)}</td><td>{html.escape(a.reference)}</td>"
                         f"<td class='{'pass' if a.status == 'pass' else 'fail' if a.status == 'fail' else ''}'>"
                         f"{a.status}</td><td>{html.escape(a.detail)}</td></tr>" for a in audit)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>{CSS}</style></head><body>
<h1>{html.escape(title)}</h1>
<div class="sub">Run {html.escape(run_id or '–')} · generated {when} · TCP Congestion Control Visualizer v{D.SIMULATOR_VERSION}
· all values computed from this run's simulation trace</div>
<div class="kpis">{kpi_html}</div>
<h2>Configuration</h2>{_table(cfg_rows)}
<h2>Per-flow results</h2>{_table(pf)}
<h2>Charts</h2>{''.join(chart_html)}
<h2>Congestion events explained</h2>
<table><thead><tr><th>t (s)</th><th>event</th><th>flow</th><th>explanation</th></tr></thead><tbody>{ev_rows}</tbody></table>{more}
<h2>Trace audit</h2>
<table><thead><tr><th>check</th><th>reference</th><th>status</th><th>detail</th></tr></thead><tbody>{audit_rows}</tbody></table>
<h2>Metric definitions</h2>
<p class="note">Goodput counts unique in-order bytes delivered to the receiving application (retransmissions excluded).
Link utilisation counts every byte serialised on the bottleneck, including retransmissions and cross traffic.
Packet loss = dropped TCP data packets / TCP data packets transmitted. RTT samples come from ACKs of segments that were
not retransmitted (Karn). The simulator is a segment-level model without SACK, delayed ACKs or pacing; results show
modelled behaviour, not measurements of a real TCP stack.</p>
</body></html>"""
