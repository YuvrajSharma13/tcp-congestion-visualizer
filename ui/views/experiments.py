"""Page 6 - Experiment history, comparison of saved runs, exports and reports."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config.validation import ConfigValidationError
from reporting.export_csv import events_csv, metrics_csv, table_csv, throughput_csv, timeseries_csv
from reporting.export_json import config_json, load_config_json
from reporting.report import build_report
from reporting.static_plots import FIGURES, render as render_static
from ui import state
from ui.components import describe, hero, load_into_editor
from visualization.theme import TEMPLATE, flow_color


def _session_table(h) -> pd.DataFrame:
    return pd.DataFrame([{
        "run_id": r.run_id, "time": r.created, "source": r.source, "label": r.label,
        "algorithms": "+".join(r.config.algorithms), "flows": r.config.n_flows, "seed": r.config.seed,
        "bandwidth Mbps": r.config.bandwidth_mbps, "delay ms": r.config.delay_ms, "buffer": r.config.buffer_packets,
        "loss prob": r.config.loss_prob, "goodput Mbps": r.metrics.aggregate_goodput_mbps,
        "link util %": r.metrics.link_utilisation_pct, "loss %": r.metrics.loss_pct,
        "avg RTT ms": r.metrics.avg_rtt_ms, "timeouts": r.metrics.timeouts, "fast retx": r.metrics.fast_retransmits,
        "Jain": r.metrics.jain_index, "trace kept": r.result is not None,
    } for r in reversed(h)])


def render() -> None:
    hero("Analyse", "Experiments & Reports",
         "Session history holds full traces for your most recent runs. The local history database "
         "(data/experiments.db, SQLite) keeps configurations and metrics across sessions. Every export is generated "
         "from actual simulation data.")
    tab_s, tab_db, tab_p = st.tabs(["Session history & exports", "Saved history (database)", "Presets & import"])
    with tab_s:
        _session()
    with tab_db:
        _database()
    with tab_p:
        _presets()


def _session() -> None:
    h = state.history()
    if not h:
        st.info("No runs in this session yet.")
        return
    df = _session_table(h)
    st.dataframe(df, hide_index=True, width="stretch", height=260,
                 column_config={c: st.column_config.NumberColumn(format="%.2f")
                                for c in ("goodput Mbps", "link util %", "loss %", "avg RTT ms", "Jain")})
    st.download_button("Download session history (CSV)", table_csv(df), "session_history.csv", "text/csv")

    st.markdown("#### Compare runs")
    ids = st.multiselect("Runs", df["run_id"].tolist(), default=df["run_id"].tolist()[:2], key="exp_cmp")
    if ids:
        sub = df[df["run_id"].isin(ids)]
        metric = st.segmented_control("Metric", ["goodput Mbps", "link util %", "loss %", "avg RTT ms", "timeouts"],
                                      default="goodput Mbps", key="exp_metric") or "goodput Mbps"
        fig = go.Figure(go.Bar(x=sub["run_id"], y=sub[metric], marker=dict(color=[flow_color(i) for i in range(len(sub))],
                                                                           cornerradius=4),
                               text=[f"{v:.2f}" for v in sub[metric]], textposition="outside"))
        fig.update_layout(template=TEMPLATE, height=280, title=metric, showlegend=False, xaxis_title="")
        st.plotly_chart(fig, width="stretch")

    st.markdown("#### Export a run")
    with_trace = [r for r in reversed(h) if r.result is not None]
    if not with_trace:
        st.caption("Full traces are kept only for the latest runs; re-run an experiment to export it.")
        return
    labels = {r.run_id: f"{r.run_id} · {r.source} · {r.label[:70]}" for r in with_trace}
    rid = st.selectbox("Run", list(labels), format_func=labels.get, key="exp_run")
    rec = state.get_record(rid)
    res, m, cfg = rec.result, rec.metrics, rec.config
    st.caption(describe(cfg))
    c = st.columns(4)
    c[0].download_button("Event log (CSV)", events_csv(res), f"{rid}_events.csv", "text/csv", width="stretch")
    c[1].download_button("Metrics (CSV)", metrics_csv(m, rid), f"{rid}_metrics.csv", "text/csv", width="stretch")
    c[2].download_button("Time series (CSV)", timeseries_csv(res), f"{rid}_samples.csv", "text/csv", width="stretch")
    c[3].download_button("Goodput series (CSV)", throughput_csv(res), f"{rid}_goodput.csv", "text/csv",
                         width="stretch")
    c = st.columns(4)
    c[0].download_button("Configuration (JSON)", config_json(cfg, run_id=rid, metrics=m.to_dict()),
                         f"{rid}_config.json", "application/json", width="stretch")
    if c[1].button("Build HTML report", width="stretch"):
        with st.spinner("Building report..."):
            st.session_state.exp_report = (rid, build_report(res, m, rid))
    rep = st.session_state.get("exp_report")
    if rep and rep[0] == rid:
        c[2].download_button("Download HTML report", rep[1], f"{rid}_report.html", "text/html", width="stretch",
                             type="primary")
    st.markdown("**Publication-style figures** (Matplotlib, works offline)")
    f1, f2, f3 = st.columns([2, 1, 1])
    kind = f1.selectbox("Figure", FIGURES, key="exp_fig")
    fmt = f2.radio("Format", ["png", "svg"], horizontal=True, key="exp_fmt")
    data = render_static(res, kind, fmt)
    f3.download_button(f"Download {fmt.upper()}", data, f"{rid}_{kind}.{fmt}",
                       "image/png" if fmt == "png" else "image/svg+xml", width="stretch")
    if fmt == "png":
        st.image(data, width=640)


def _database() -> None:
    s = state.store()
    if s is None:
        st.error(f"The history database could not be opened: {st.session_state.get('store_error')}")
        return
    df = s.runs_table()
    if df.empty:
        st.info("The history database is empty. Runs are saved automatically while 'Save to history DB' is on "
                "(Simulation Lab).")
        return
    st.caption(f"{len(df)} saved runs in {s.path}")
    st.dataframe(df, hide_index=True, width="stretch", height=320)
    st.download_button("Download saved history (CSV)", table_csv(df), "experiment_history.csv", "text/csv")
    c1, c2, c3 = st.columns([2, 1, 1])
    rid = c1.selectbox("Saved run", df["run_id"].tolist(), key="db_run")
    if c2.button("Load its configuration into the Lab", width="stretch"):
        cfg, _ = s.get_run(rid)
        load_into_editor("lab", cfg)
        st.session_state.lab_config = cfg
        st.success("Loaded - open the Simulation Lab and run it to reproduce the result.")
    if c3.button("Delete run", width="stretch"):
        s.delete_run(rid)
        st.rerun()
    with st.popover("Clear all saved runs"):
        st.warning("This permanently deletes every saved run from the local database.")
        if st.button("Yes, delete all", type="primary"):
            s.clear_runs()
            st.rerun()


def _presets() -> None:
    s = state.store()
    st.markdown("#### Import a configuration")
    up = st.file_uploader("Experiment JSON (exported from this app)", type=["json"], key="exp_upload")
    if up is not None:
        try:
            cfg, meta = load_config_json(up.getvalue())
            st.success(f"Valid configuration: {describe(cfg)}")
            if st.button("Load into Simulation Lab", key="exp_up_load"):
                load_into_editor("lab", cfg)
                st.session_state.lab_config = cfg
                st.success("Loaded.")
        except ConfigValidationError as exc:
            st.error("\n".join(exc.errors))
    st.markdown("#### Saved presets")
    if s is None:
        st.error("Preset storage unavailable.")
        return
    p = s.list_presets()
    if p.empty:
        st.caption("No presets yet - save one from the Simulation Lab.")
        return
    st.dataframe(p, hide_index=True, width="stretch")
    name = st.selectbox("Preset", p["name"].tolist(), key="exp_preset")
    cfg = s.load_preset(name)
    st.caption(describe(cfg))
    c1, c2, c3 = st.columns(3)
    if c1.button("Load into Simulation Lab", key="exp_preset_load", width="stretch"):
        load_into_editor("lab", cfg)
        st.session_state.lab_config = cfg
        st.success("Loaded.")
    c2.download_button("Export JSON", config_json(cfg, name=name), f"{name}.json", "application/json",
                       width="stretch")
    if c3.button("Delete preset", width="stretch"):
        s.delete_preset(name)
        st.rerun()
