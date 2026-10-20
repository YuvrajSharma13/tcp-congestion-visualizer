"""Page 5 - Scenario Lab."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics.scenarios import SCENARIOS, custom_scenario, run_scenario
from config import defaults as D
from ui import state
from ui.components import check_card, describe, hero, load_into_editor
from visualization import charts


def render() -> None:
    hero("Analyse", "Scenario Lab",
         "Ready-made experiments from the project plan. Each one sets valid parameters, says what to look for, "
         "and afterwards checks the measured results against that expectation - without assuming any algorithm wins.")

    options = SCENARIOS + [custom_scenario(state.lab_config())]
    titles = [f"{i + 1}. {s.title}" for i, s in enumerate(options)]
    left, right = st.columns([1, 2.2])
    with left:
        idx = st.radio("Scenario", range(len(options)), format_func=lambda i: titles[i], key="sc_idx")
    sc = options[idx]
    with right:
        st.markdown(f"### {sc.title}")
        st.markdown(sc.summary)
        st.markdown("**What to observe**")
        for o in sc.observe:
            st.markdown(f"- {o}")
        alg = "reno"
        if not sc.fixed_algorithms and sc.id != "custom":
            alg = st.segmented_control("Algorithm", D.ALGORITHMS, default="reno", format_func=D.ALGORITHM_LABELS.get,
                                       key=f"sc_alg_{sc.id}") or "reno"
        plans = sc.build(alg)
        st.caption(f"{len(plans)} run(s): " + " | ".join(f"**{lab}** – {describe(c)}" for lab, c in plans))
        c1, c2 = st.columns(2)
        go = c1.button("Run scenario", type="primary", width="stretch")
        if c2.button("Open first configuration in Simulation Lab", width="stretch"):
            load_into_editor("lab", plans[0][1])
            st.session_state.lab_config = plans[0][1]
            st.success("Loaded. Open the Simulation Lab page to edit and run it.")

    if go:
        bar = st.progress(0.0, text="Starting...")
        runs, checks = run_scenario(sc, alg, state.simulate,
                                    progress=lambda i, n, lab: bar.progress(i / n, text=f"Simulating {lab}..."))
        bar.empty()
        for r in runs:
            state.record_run(r.config, r.result, f"{sc.title}: {r.label}", "scenario")
        st.session_state.sc_last = (sc.id, alg, runs, checks)

    last = st.session_state.get("sc_last")
    if not last or last[0] != sc.id:
        return
    _, alg, runs, checks = last
    st.divider()
    st.markdown("#### Expected vs. observed")
    for c in checks:
        check_card(c.expectation, c.observed, c.status)
    st.markdown("#### Results")
    rows = []
    for r in runs:
        m = r.metrics
        rows.append({"run": r.label, "goodput Mbps": m.aggregate_goodput_mbps, "link util %": m.link_utilisation_pct,
                     "loss %": m.loss_pct, "avg RTT ms": m.avg_rtt_ms, "fast retx": m.fast_retransmits,
                     "timeouts": m.timeouts, "Jain": m.jain_index if m.n_flows > 1 else None})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={k: st.column_config.NumberColumn(format="%.2f")
                                for k in ("goodput Mbps", "link util %", "loss %", "avg RTT ms", "Jain")})
    tabs = st.tabs([r.label for r in runs])
    for t, r in zip(tabs, runs):
        with t:
            fig, note = charts.cwnd_chart(r.result, height=360)
            st.plotly_chart(fig, width="stretch", key=f"sc_cw_{r.label}")
            if note:
                st.caption(note)
            if r.config.n_flows > 1:
                st.plotly_chart(charts.per_flow_bars(r.metrics), width="stretch", key=f"sc_pf_{r.label}")
            else:
                st.plotly_chart(charts.queue_chart(r.result), width="stretch", key=f"sc_q_{r.label}")
