"""Page 4 - Algorithm comparison under identical conditions."""

from __future__ import annotations

import streamlit as st

from analytics.comparison import (METRIC_INFO, comparison_table, fairness_over_time, interpret, recovery_episodes,
                                  run_comparison)
from config import defaults as D
from reporting.export_csv import table_csv
from ui import state
from ui.components import config_editor, describe, hero, show_errors
from visualization import charts

KEY = "cmp"


def render() -> None:
    hero("Analyse", "Algorithm Comparison",
         "Run the same network - same bandwidth, delay, buffer, loss probability, flow start times and random "
         "seed - once per algorithm. With several flows, every flow uses the algorithm being tested.")

    algs = st.pills("Algorithms to compare", D.ALGORITHMS, selection_mode="multi", default=list(D.ALGORITHMS),
                    format_func=D.ALGORITHM_LABELS.get, key="cmp_algs")
    with st.expander("Network configuration (starts from the Simulation Lab settings)", expanded=False):
        cfg, errs = config_editor(KEY, state.lab_config(), per_flow_algorithms=False)
    if errs:
        show_errors(errs)
    run = st.button("Run comparison", type="primary", disabled=cfg is None or not algs)
    if run:
        bar = st.progress(0.0, text="Starting...")

        def prog(i, n, a):
            bar.progress(i / n, text=f"Simulating {D.ALGORITHM_LABELS.get(a, a)}..." if a != "done" else "Done")

        runs = run_comparison(cfg, list(algs), progress=prog, runner=state.simulate)
        for r in runs:
            state.record_run(r.config, r.result, f"comparison: {D.ALGORITHM_LABELS[r.algorithm]}", "comparison")
        st.session_state.cmp_runs = runs
        st.session_state.cmp_base = cfg
        bar.empty()

    runs = st.session_state.get("cmp_runs")
    if not runs:
        st.info("Choose algorithms and press **Run comparison**.")
        return
    base = st.session_state.cmp_base
    st.caption("Compared under: " + describe(base).split(" · ", 1)[1])
    table = comparison_table(runs)

    st.markdown("#### Congestion window")
    clip = st.checkbox("Clip fast-recovery inflation", value=True, key="cmp_clip")
    st.plotly_chart(charts.overlay_cwnd(runs, clip), width="stretch")

    st.markdown("#### Summary")
    show = table.copy()
    show["algorithm"] = show["algorithm"].map(D.ALGORITHM_LABELS)
    st.dataframe(show, hide_index=True, width="stretch", column_config={
        "goodput_mbps": st.column_config.NumberColumn("goodput (Mbps)", format="%.2f"),
        "link_util_pct": st.column_config.NumberColumn("link util %", format="%.1f"),
        "loss_pct": st.column_config.NumberColumn("loss %", format="%.2f"),
        "avg_rtt_ms": st.column_config.NumberColumn("avg RTT ms", format="%.1f"),
        "avg_queue_pkts": st.column_config.NumberColumn("avg queue", format="%.1f"),
        "avg_cwnd": st.column_config.NumberColumn("avg cwnd", format="%.1f"),
        "median_regain_s": st.column_config.NumberColumn("median recovery s", format="%.2f",
                                                         help="Time to regain 90% of the pre-loss cwnd"),
        "unrecovered_events": st.column_config.NumberColumn("not regained",
                                                            help="Losses after which cwnd never regained 90% "
                                                                 "before the next loss or the end"),
        "startup_s": st.column_config.NumberColumn("startup s", format="%.2f",
                                                   help="First time goodput reached 80% of capacity"),
        "jain_index": st.column_config.NumberColumn("Jain", format="%.3f"),
    })
    st.download_button("Download comparison table (CSV)", table_csv(table), "comparison.csv", "text/csv")

    metrics = ["goodput_mbps", "avg_rtt_ms", "loss_pct", "link_util_pct", "timeouts", "median_regain_s"]
    cols = st.columns(3)
    for i, mkey in enumerate(metrics):
        name, unit, _ = METRIC_INFO[mkey]
        with cols[i % 3]:
            st.plotly_chart(charts.metric_bars(table, mkey, name, unit), width="stretch")
    st.plotly_chart(charts.metric_bars(table, "fast_retransmits", "Fast retransmits", ""), width="stretch")

    st.markdown("#### What the data shows")
    for n in interpret(table, base):
        st.markdown(f"- {n}")

    with st.expander("Recovery episodes (every fast retransmit / timeout, flow 0)"):
        sel = st.selectbox("Algorithm", [r.algorithm for r in runs], format_func=D.ALGORITHM_LABELS.get)
        r = next(x for x in runs if x.algorithm == sel)
        st.dataframe(recovery_episodes(r.result, 0), hide_index=True, width="stretch")
    if base.n_flows > 1:
        st.markdown("#### Fairness between flows")
        cols = st.columns(len(runs))
        for c, r in zip(cols, runs):
            with c:
                st.markdown(f"**{D.ALGORITHM_LABELS[r.algorithm]}** · J = {r.metrics.jain_index:.3f}")
                st.plotly_chart(charts.per_flow_bars(r.metrics, "Per-flow goodput"), width="stretch",
                                key=f"pf_{r.algorithm}")
                fo = fairness_over_time(r.result)
                if not fo.empty:
                    st.plotly_chart(charts.jain_chart(fo), width="stretch", key=f"jt_{r.algorithm}")
        st.caption("Jain's index measures equality of shares (1 = equal); it says nothing about total efficiency.")
