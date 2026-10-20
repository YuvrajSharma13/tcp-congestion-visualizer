"""Validation: RFC rule probes, trace audits, limitations, real Linux trace comparison."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config.validation import make_config
from reporting.export_csv import table_csv
from ui import state
from ui.components import describe, hero
from validation.real_trace import TraceFormatError, compare, main_connection, parse_ss_trace, sample_simulation
from validation.rfc_checks import LIMITATIONS, audit_trace, rule_probes
from visualization.theme import ALGO_COLOR, MUTED, TEMPLATE

TRACE_DIR = Path(__file__).resolve().parents[2] / "data" / "real_traces"


def _status_table(rows) -> pd.DataFrame:
    df = pd.DataFrame([r.__dict__ for r in rows])
    df.insert(0, "", df["status"].map({"pass": "✅", "fail": "❌"}).fillna("➖"))
    return df


def render() -> None:
    hero("Research", "Validation",
         "Checks that the simulator follows the rules it claims to implement, the assumptions that limit comparison "
         "with a real TCP stack, and an optional comparison with real Linux traces.")
    t1, t2, t3 = st.tabs(["RFC checks", "Assumptions & limitations", "Real Linux traces"])
    with t1:
        probes = rule_probes()
        n_pass = sum(p.status == "pass" for p in probes)
        st.markdown(f"#### Rule probes · {n_pass}/{len(probes)} pass")
        st.caption("Each probe drives an algorithm object with a scripted ACK sequence and compares cwnd/ssthresh "
                   "with the cited RFC rule.")
        df = _status_table(probes)
        st.dataframe(df, hide_index=True, width="stretch")
        st.markdown("#### Trace audit")
        runs = [r for r in reversed(state.history()) if r.result is not None]
        if not runs:
            if st.button("Run a mixed four-algorithm audit run"):
                cfg = make_config(["tahoe", "reno", "newreno", "cubic"], n_flows=4, duration_s=15, buffer_packets=20,
                                  loss_prob=0.003)
                state.record_run(cfg, state.simulate(cfg), "validation audit", "validation")
                st.rerun()
            st.caption("No session runs to audit yet.")
        else:
            labels = {r.run_id: f"{r.run_id} · {describe(r.config)[:90]}" for r in runs}
            rid = st.selectbox("Run to audit", list(labels), format_func=labels.get, key="val_run")
            audit = audit_trace(state.get_record(rid).result)
            n_fail = sum(a.status == "fail" for a in audit)
            (st.success if n_fail == 0 else st.error)(
                f"{sum(a.status == 'pass' for a in audit)} checks passed, {n_fail} failed, "
                f"{sum(a.status not in ('pass', 'fail') for a in audit)} not applicable.")
            adf = _status_table(audit)
            st.dataframe(adf, hide_index=True, width="stretch")
            full = pd.concat([df.assign(scope="rule probe"), adf.assign(scope=f"trace {rid}")])
            st.download_button("Download validation summary (CSV)", table_csv(full), "validation_summary.csv",
                               "text/csv")
        st.caption("The automated pytest suite (tests/) covers these rules and many more; run `python -m pytest -q`.")
    with t2:
        st.dataframe(pd.DataFrame(LIMITATIONS, columns=["Assumption / simplification", "Consequence"]),
                     hide_index=True, width="stretch")
        st.markdown("Not implemented: SACK, delayed ACKs, ECN/AQM, BBR or delay-based algorithms, multi-hop "
                    "topologies, connection setup, HyStart++, pacing. See docs/simulation_assumptions.md.")
    with t3:
        _real()


def _real() -> None:
    st.markdown("Import a trace captured on Linux/WSL with `tools/capture_ss_trace.sh` (iperf3 + `ss -tin`). "
                "The app only reads the file; it never touches your TCP stack. Two sample captures are bundled: "
                "a real Linux 6.18 kernel sending through a 10 Mbit/s token-bucket bottleneck on loopback "
                "(≈60 KB queue, MTU 1500, sampled every 50 ms).")
    samples = sorted(p.name for p in TRACE_DIR.glob("*.txt"))
    c1, c2 = st.columns(2)
    src = c1.selectbox("Bundled sample", ["—"] + samples, key="rt_sample")
    up = c2.file_uploader("…or upload your own capture", type=["txt", "log"], key="rt_up")
    text = None
    if up is not None:
        text = up.getvalue().decode("utf-8", errors="replace")
    elif src != "—":
        text = (TRACE_DIR / src).read_text()
    if text is None:
        return
    try:
        real = main_connection(parse_ss_trace(text))
    except TraceFormatError as exc:
        st.error(str(exc))
        return
    alg = real["algorithm"].iloc[0]
    st.caption(f"{len(real)} samples over {real['t'].max():.1f} s · algorithm `{alg}` · MSS {real['mss'].iloc[0]:.0f} B")
    sim_alg = alg if alg in ("reno", "cubic") else "reno"
    d1, d2, d3, d4 = st.columns(4)
    bw = d1.number_input("Sim bandwidth (Mbps)", 0.1, 1000.0, 10.0, key="rt_bw")
    delay = d2.number_input("Sim one-way delay (ms)", 0.0, 1000.0, 0.0, key="rt_delay")
    buf = d3.number_input("Sim buffer (packets)", 1, 10000, 40, key="rt_buf")
    salg = d4.selectbox("Sim algorithm", ["tahoe", "reno", "newreno", "cubic"],
                        index=["tahoe", "reno", "newreno", "cubic"].index(sim_alg), key="rt_alg")
    dur = float(min(max(real["t"].max(), 1.0), 120.0))
    cfg = make_config(salg, duration_s=dur, bandwidth_mbps=bw, delay_ms=delay, buffer_packets=int(buf),
                      mss_bytes=int(real["mss"].iloc[0]), min_rto_s=0.2, record_packet_events=False)
    res = state.simulate(cfg)
    interval = float(real["t"].diff().median())
    sim = sample_simulation(res, interval)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=real["t"], y=real["cwnd"], mode="lines", name=f"Linux {alg} (ss -ti)",
                             line=dict(color=ALGO_COLOR["cubic" if alg == "cubic" else "reno"], width=2)))
    fig.add_trace(go.Scatter(x=sim["t"], y=sim["cwnd"], mode="lines", name=f"simulated {salg} (sampled alike)",
                             line=dict(color=MUTED, width=1.5, dash="dot")))
    fig.update_layout(template=TEMPLATE, height=360, title="cwnd: real kernel vs simulator", yaxis_title="segments",
                      xaxis_title="time (s)")
    st.plotly_chart(fig, width="stretch")
    st.dataframe(compare(real, res), hide_index=True, width="stretch")
    st.caption("Compare shapes and summary statistics only. Linux uses SACK, PRR, delayed ACKs, pacing, "
               "HyStart++ and TSO; its cwnd is not expected to match the simulator's value for value. The sampled "
               "simulator curve hides events shorter than the sampling interval, just like ss.")
