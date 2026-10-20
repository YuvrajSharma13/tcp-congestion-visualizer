"""Reusable dashboard components: styling, KPI cards, configuration editor, downloads."""

from __future__ import annotations

import html
import math
from dataclasses import replace

import streamlit as st

from config import defaults as D
from config.validation import (ConfigValidationError, CrossTrafficConfig, FlowConfig, LossBurst, SimulationConfig)
from visualization.theme import ALGO_COLOR

CSS = """
<style>
:root { --tv-surface:#161a21; --tv-line:#262b35; --tv-text:#e8e9ec; --tv-text2:#a7adb9; --tv-accent:#3987e5; }
.block-container { padding-top: 3.6rem; max-width: 1400px; }
h1, h2, h3 { letter-spacing: -0.01em; }
.tv-hero { display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; margin-bottom: 4px; }
.tv-hero h1 { margin:0; font-size: 1.9rem; }
.tv-eyebrow { color: var(--tv-accent); font-size: .78rem; font-weight: 600; letter-spacing: .12em;
  text-transform: uppercase; }
.tv-sub { color: var(--tv-text2); font-size: .95rem; max-width: 900px; }
.tv-kpis { display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin: 12px 0 6px; }
.tv-kpi { background: var(--tv-surface); border: 1px solid var(--tv-line); border-radius: 10px; padding: 10px 14px; }
.tv-kpi .l { color: var(--tv-text2); font-size: .74rem; text-transform: uppercase; letter-spacing: .06em; }
.tv-kpi .v { font-size: 1.45rem; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--tv-text);
  line-height: 1.25; }
.tv-kpi .h { color: var(--tv-text2); font-size: .76rem; }
.tv-pill { display:inline-block; padding: 1px 9px; border-radius: 999px; font-size: .75rem; font-weight: 600;
  border: 1px solid var(--tv-line); margin-right: 6px; }
.tv-algo-dot { display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:6px; vertical-align: 0; }
.tv-check { border-left: 3px solid var(--tv-line); padding: 6px 12px; margin: 6px 0; background: var(--tv-surface);
  border-radius: 0 8px 8px 0; }
.tv-check.consistent { border-left-color: #3fbf7f; } .tv-check.notobserved { border-left-color: #ffb020; }
.tv-check.info { border-left-color: #3987e5; }
.tv-check .s { font-size: .72rem; text-transform: uppercase; letter-spacing: .07em; color: var(--tv-text2); }
.tv-explain { background: var(--tv-surface); border: 1px solid var(--tv-line); border-radius: 10px; padding: 12px 16px; }
div[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(eyebrow: str, title: str, sub: str) -> None:
    st.markdown(f"<div class='tv-eyebrow'>{html.escape(eyebrow)}</div><div class='tv-hero'><h1>{html.escape(title)}"
                f"</h1></div><div class='tv-sub'>{sub}</div>", unsafe_allow_html=True)


def fmt(v, digits: int = 2, unit: str = "") -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "–"
    if isinstance(v, int):
        return f"{v:,}{unit}"
    return f"{v:,.{digits}f}{unit}"


def kpis(items: list[tuple[str, str, str]]) -> None:
    cells = "".join(f"<div class='tv-kpi'><div class='l'>{html.escape(l)}</div><div class='v'>{html.escape(v)}</div>"
                    f"<div class='h'>{html.escape(h)}</div></div>" for l, v, h in items)
    st.markdown(f"<div class='tv-kpis'>{cells}</div>", unsafe_allow_html=True)


def metric_kpis(m, cfg) -> None:
    kpis([
        ("Goodput", fmt(m.aggregate_goodput_mbps, 2, " Mbps"), f"of {cfg.bandwidth_mbps:g} Mbps capacity"),
        ("Link utilisation", fmt(m.link_utilisation_pct, 1, " %"), "bytes serialised / capacity"),
        ("Packet loss", fmt(m.loss_pct, 2, " %"), f"{m.tcp_drops:,} of {m.tcp_packets_sent:,} packets"),
        ("Average RTT", fmt(m.avg_rtt_ms, 1, " ms"), f"base {m.base_rtt_ms:.1f} ms"),
        ("Fast retransmits", fmt(m.fast_retransmits), f"{m.retx_packets:,} retransmitted packets"),
        ("Timeouts", fmt(m.timeouts), "RTO expiries"),
        ("Avg / peak cwnd", f"{fmt(m.avg_cwnd, 1)} / {fmt(m.peak_cwnd, 0)}", "segments"),
        ("Jain's index", fmt(m.jain_index, 3) if m.n_flows > 1 else "–",
         "per-flow goodput equality" if m.n_flows > 1 else "single flow"),
    ])


def algo_badge(alg: str) -> str:
    return (f"<span class='tv-pill'><span class='tv-algo-dot' style='background:{ALGO_COLOR[alg]}'></span>"
            f"{D.ALGORITHM_LABELS[alg]}</span>")


def show_errors(errors: list[str]) -> None:
    st.error("This configuration cannot be simulated:\n\n" + "\n".join(f"- {e}" for e in errors))


def check_card(statement: str, observed: str, status: str) -> None:
    cls = status.replace(" ", "")
    label = {"consistent": "Consistent with expectation", "not observed": "Not observed in this run",
             "info": "Observation"}.get(status, status)
    st.markdown(f"<div class='tv-check {cls}'><div class='s'>{label}</div><b>{html.escape(statement)}</b><br>"
                f"<span style='color:var(--tv-text2)'>{html.escape(observed)}</span></div>", unsafe_allow_html=True)


# ------------------------------------------------------------- config editor
def load_into_editor(key: str, cfg: SimulationConfig) -> None:
    """Write a configuration into the editor's widget state (call before the editor renders, then rerun)."""
    ss = st.session_state
    ss[f"{key}_nflows"] = cfg.n_flows
    for i in range(D.LIMITS["flows"][1]):
        f = cfg.flows[min(i, cfg.n_flows - 1)]
        ss[f"{key}_alg{i}"] = f.algorithm
        ss[f"{key}_start{i}"] = float(f.start_time_s) if i < cfg.n_flows else 0.0
    ss[f"{key}_bw"] = float(cfg.bandwidth_mbps)
    ss[f"{key}_delay"] = float(cfg.delay_ms)
    ss[f"{key}_mss"] = int(cfg.mss_bytes)
    ss[f"{key}_buf"] = int(cfg.buffer_packets)
    ss[f"{key}_loss"] = float(cfg.loss_prob * 100)
    ss[f"{key}_dur"] = float(cfg.duration_s)
    ss[f"{key}_seed"] = int(cfg.seed)
    ss[f"{key}_icwnd"] = float(cfg.flows[0].initial_cwnd)
    ss[f"{key}_issth"] = float(cfg.flows[0].initial_ssthresh)
    ss[f"{key}_rwnd"] = int(cfg.receiver_window)
    ss[f"{key}_minrto"] = float(cfg.min_rto_s * 1000)
    ss[f"{key}_timer"] = cfg.newreno_timer_variant
    ss[f"{key}_cc"] = float(cfg.cubic_c)
    ss[f"{key}_cb"] = float(cfg.cubic_beta)
    ss[f"{key}_cfc"] = bool(cfg.cubic_fast_convergence)
    ss[f"{key}_ct"] = bool(cfg.cross_traffic.enabled)
    ss[f"{key}_ctrate"] = float(cfg.cross_traffic.rate_mbps or 2.0)
    ss[f"{key}_ctpat"] = cfg.cross_traffic.pattern
    ss[f"{key}_burst"] = bool(cfg.loss_bursts)
    ss[f"{key}_bstart"] = float(cfg.loss_bursts[0].start_s) if cfg.loss_bursts else 5.0
    ss[f"{key}_bdur"] = float(cfg.loss_bursts[0].duration_s * 1000) if cfg.loss_bursts else 400.0
    ss[f"{key}_pkt"] = bool(cfg.record_packet_events)
    ss[f"{key}_forced"] = cfg.forced_drops
    ss[f"{key}_extra_bursts"] = cfg.loss_bursts[1:]


def config_editor(key: str, base: SimulationConfig, per_flow_algorithms: bool = True
                  ) -> tuple[SimulationConfig | None, list[str]]:
    ss = st.session_state
    if f"{key}_bw" not in ss:
        load_into_editor(key, base)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Network**")
        bw = st.number_input("Bottleneck bandwidth (Mbps)", 0.01, 1000.0, step=1.0, key=f"{key}_bw",
                             help="Capacity of the shared link. Serialization time = packet size × 8 / bandwidth.")
        delay = st.number_input("One-way propagation delay (ms)", 0.0, 2000.0, step=5.0, key=f"{key}_delay",
                                help="Applies to data (sender → receiver) and to ACKs (receiver → sender).")
        buf = st.number_input("Buffer capacity (packets)", 1, 10_000, step=5, key=f"{key}_buf",
                              help="Packets that can wait at the bottleneck; arrivals to a full buffer are dropped.")
    with c2:
        st.markdown("**Traffic**")
        loss = st.number_input("Random loss (% of data packets)", 0.0, 50.0, step=0.1, format="%.3f",
                               key=f"{key}_loss", help="Applied to TCP data packets on the link; ACKs are never lost.")
        mss = st.number_input("Packet size / MSS (bytes)", 64, 9000, step=100, key=f"{key}_mss")
        dur = st.number_input("Duration (s)", 0.1, 300.0, step=5.0, key=f"{key}_dur")
    with c3:
        st.markdown("**TCP & reproducibility**")
        icwnd = st.number_input("Initial cwnd (segments)", 1.0, 1000.0, step=1.0, key=f"{key}_icwnd")
        issth = st.number_input("Initial ssthresh (segments)", 2.0, 1_000_000.0, step=8.0, key=f"{key}_issth")
        seed = st.number_input("Random seed", 0, 2**32 - 1, step=1, key=f"{key}_seed")

    st.markdown("**Flows**")
    nflows = st.number_input("Number of competing flows", 1, 10, step=1, key=f"{key}_nflows")
    flows = []
    cols = st.columns(min(int(nflows), 5))
    for i in range(int(nflows)):
        with cols[i % len(cols)]:
            if per_flow_algorithms:
                alg = st.selectbox(f"Flow {i} algorithm", D.ALGORITHMS, format_func=D.ALGORITHM_LABELS.get,
                                   key=f"{key}_alg{i}")
            else:
                alg = "reno"
            start = st.number_input(f"Flow {i} start (s)", 0.0, 300.0, step=1.0, key=f"{key}_start{i}")
            flows.append(FlowConfig(alg or "reno", float(start or 0.0), float(icwnd), float(issth)))

    with st.expander("Advanced: timers, CUBIC, cross traffic, loss bursts, recording"):
        a1, a2, a3 = st.columns(3)
        with a1:
            rwnd = st.number_input("Receiver window (segments)", 1, 1_000_000, step=100, key=f"{key}_rwnd")
            minrto = st.number_input("Minimum RTO (ms)", 1.0, 60000.0, step=50.0, key=f"{key}_minrto",
                                     help="RFC 6298 says 1 s; Linux uses 200 ms.")
            timer = st.radio("NewReno/CUBIC timer on partial ACKs", ["impatient", "slow_but_steady"],
                             key=f"{key}_timer", horizontal=True,
                             help="RFC 6582 §4: Impatient resets the RTO only on the first partial ACK.")
        with a2:
            cc_ = st.number_input("CUBIC C", 0.01, 10.0, step=0.1, key=f"{key}_cc")
            cb = st.number_input("CUBIC beta", 0.1, 0.95, step=0.05, key=f"{key}_cb")
            cfc = st.checkbox("CUBIC fast convergence", key=f"{key}_cfc")
        with a3:
            ct = st.checkbox("Unresponsive cross traffic", key=f"{key}_ct")
            ctrate = st.number_input("Cross-traffic rate (Mbps)", 0.01, 1000.0, step=0.5, key=f"{key}_ctrate",
                                     disabled=not ct)
            ctpat = st.radio("Pattern", ["cbr", "poisson"], key=f"{key}_ctpat", horizontal=True, disabled=not ct)
        b1, b2, b3 = st.columns(3)
        with b1:
            burst = st.checkbox("Loss burst (all data packets lost)", key=f"{key}_burst")
        with b2:
            bstart = st.number_input("Burst start (s)", 0.0, 300.0, step=0.5, key=f"{key}_bstart",
                                     disabled=not burst)
        with b3:
            bdur = st.number_input("Burst length (ms)", 1.0, 10000.0, step=50.0, key=f"{key}_bdur",
                                   disabled=not burst)
        pkt = st.checkbox("Record per-packet events (needed for packet playback; uses more memory)", key=f"{key}_pkt")
        forced = ss.get(f"{key}_forced", ())
        if forced:
            st.caption(f"Scripted drops kept from the loaded scenario: " +
                       ", ".join(f"flow {d.flow_id} seg {d.seq}" for d in forced))
            if st.button("Remove scripted drops", key=f"{key}_clearforced"):
                ss[f"{key}_forced"] = ()
                st.rerun()

    bursts = ((LossBurst(float(bstart or 0), float(bdur or 0) / 1000.0),) if burst else ()) + \
        tuple(ss.get(f"{key}_extra_bursts", ()))
    try:
        cfg = SimulationConfig(
            bandwidth_mbps=float(bw), delay_ms=float(delay), mss_bytes=int(mss), buffer_packets=int(buf),
            loss_prob=float(loss) / 100.0, duration_s=float(dur), seed=int(seed), flows=tuple(flows),
            receiver_window=int(rwnd), min_rto_s=float(minrto) / 1000.0,
            initial_rto_s=max(float(minrto) / 1000.0, base.initial_rto_s),
            cubic_c=float(cc_), cubic_beta=float(cb), cubic_fast_convergence=bool(cfc),
            newreno_timer_variant=timer,
            cross_traffic=CrossTrafficConfig(enabled=bool(ct), rate_mbps=float(ctrate), pattern=ctpat),
            loss_bursts=bursts, forced_drops=tuple(ss.get(f"{key}_forced", ())),
            record_packet_events=bool(pkt), sample_interval_s=base.sample_interval_s,
        )
    except (TypeError, ValueError) as exc:
        return None, [str(exc)]
    errs = cfg.validate()
    return (None if errs else cfg), errs


def bdp_panel(cfg: SimulationConfig) -> None:
    bdp = cfg.bdp_packets
    st.markdown(
        f"**Bandwidth-delay product:** {cfg.bandwidth_mbps:g} Mbps × {cfg.base_rtt_s * 1000:.2f} ms base RTT "
        f"= **{bdp:,.1f} packets** ({bdp * cfg.mss_bytes / 1024:,.0f} KiB). "
        f"A single flow needs cwnd ≈ {bdp:,.0f} segments to keep the link busy; with a "
        f"{cfg.buffer_packets}-packet buffer, losses start once total cwnd exceeds ≈ {bdp + cfg.buffer_packets + 1:,.0f}. "
        f"Buffer = {cfg.buffer_packets / bdp:.2f} × BDP." if bdp > 0 else "BDP is zero (no delay).")


def describe(cfg: SimulationConfig) -> str:
    algs = ", ".join(D.ALGORITHM_LABELS[a] for a in cfg.algorithms)
    extra = []
    if cfg.loss_bursts:
        extra.append(f"{len(cfg.loss_bursts)} loss burst(s)")
    if cfg.forced_drops:
        extra.append(f"{len(cfg.forced_drops)} scripted drop(s)")
    if cfg.cross_traffic.enabled:
        extra.append(f"{cfg.cross_traffic.rate_mbps:g} Mbps cross traffic")
    return (f"{algs} · {cfg.bandwidth_mbps:g} Mbps · {cfg.delay_ms:g} ms · buffer {cfg.buffer_packets} · "
            f"loss {cfg.loss_prob * 100:g}% · {cfg.duration_s:g} s · seed {cfg.seed}"
            + (" · " + ", ".join(extra) if extra else ""))


_ = (replace, ConfigValidationError)
