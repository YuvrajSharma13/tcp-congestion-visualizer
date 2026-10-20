"""Page 1 - Overview dashboard."""

from __future__ import annotations

import streamlit as st

from config import defaults as D
from ui import state
from ui.components import algo_badge, bdp_panel, describe, hero, metric_kpis
from visualization import charts
from visualization.topology import topology_figure


def render() -> None:
    hero("Overview", "TCP Congestion Control Visualizer",
         "An interactive discrete-event simulator for TCP Tahoe, Reno, NewReno and CUBIC. Configure a bottleneck, "
         "run it, watch packets and congestion windows evolve, compare algorithms under identical conditions and "
         "measure the outcome. Every number on these pages is computed from a real simulation trace.")

    rec = state.latest()
    cfg = rec.config if rec else state.lab_config()
    st.subheader("Network topology")
    st.plotly_chart(topology_figure(cfg, height=330), width="stretch", config={"displayModeBar": False})
    st.caption(("Latest run: " if rec else "Current Simulation Lab configuration (not yet run): ") + describe(cfg))

    st.subheader("Latest experiment")
    if rec is None:
        st.info("No simulation has been run in this session yet, so there are no statistics to show. "
                "Open the **Simulation Lab** and press *Run simulation*, or launch a ready-made experiment in the "
                "**Scenario Lab**.")
        if st.button("Run the current configuration now", type="primary"):
            with st.spinner("Simulating..."):
                res = state.simulate(cfg)
            state.record_run(cfg, res, "current configuration", "overview")
            st.rerun()
        bdp_panel(cfg)
        return

    m = rec.metrics
    st.markdown(f"Run **{rec.run_id}** · {rec.source} · {rec.label} · at {rec.created} &nbsp; "
                + " ".join(algo_badge(a) for a in dict.fromkeys(rec.config.algorithms)), unsafe_allow_html=True)
    total = st.session_state.get("total_runs", 0)
    st.caption(f"Total simulation runs this session: {total} · simulator v{D.SIMULATOR_VERSION} · "
               f"{rec.result.run_info['events_processed']:,} events in {rec.result.run_info['wall_time_s']:.2f} s")
    metric_kpis(m, rec.config)
    fig, note = charts.cwnd_chart(rec.result, height=360)
    st.plotly_chart(fig, width="stretch")
    if note:
        st.caption(note)
    bdp_panel(rec.config)

    h = state.history()
    if len(h) > 1:
        st.subheader("Recent runs (this session)")
        import pandas as pd
        rows = [{"run": r.run_id, "time": r.created, "source": r.source, "label": r.label,
                 "algorithms": "+".join(r.config.algorithms), "goodput Mbps": r.metrics.aggregate_goodput_mbps,
                 "loss %": r.metrics.loss_pct, "avg RTT ms": r.metrics.avg_rtt_ms, "timeouts": r.metrics.timeouts}
                for r in reversed(h[-8:])]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"goodput Mbps": st.column_config.NumberColumn(format="%.2f"),
                                    "loss %": st.column_config.NumberColumn(format="%.2f"),
                                    "avg RTT ms": st.column_config.NumberColumn(format="%.1f")})
