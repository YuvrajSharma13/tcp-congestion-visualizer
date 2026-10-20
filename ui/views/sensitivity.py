"""Sensitivity analysis: sweep one parameter over several seeds."""

from __future__ import annotations

import streamlit as st

from analytics.sensitivity import MAX_RUNS, RESPONSES, SWEEPABLE, parse_values, run_sensitivity, summarize
from config import defaults as D
from reporting.export_csv import table_csv
from ui import state
from ui.components import describe, hero
from visualization import charts

DEFAULT_VALUES = {"buffer_packets": "5, 10, 20, 35, 60, 100", "delay_ms": "5, 10, 20, 40, 80",
                  "loss_prob": "0, 0.001, 0.005, 0.01, 0.02", "bandwidth_mbps": "2, 5, 10, 20, 40"}


def render() -> None:
    hero("Analyse", "Sensitivity Analysis",
         "Vary one parameter, repeat every point with several seeds, and see the mean with a 95% confidence "
         "interval. One random run is an anecdote; the spread tells you how much of a difference is noise.")
    base = state.lab_config()
    st.caption("Base configuration (from the Simulation Lab): " + describe(base))
    c1, c2 = st.columns(2)
    param = c1.selectbox("Parameter to vary", list(SWEEPABLE), format_func=lambda p: SWEEPABLE[p][0], key="sens_param")
    text = c2.text_input("Values (comma list or start:stop:step)", DEFAULT_VALUES[param], key=f"sens_vals_{param}")
    c3, c4, c5 = st.columns([2, 1, 1])
    algs = c3.pills("Algorithms", D.ALGORITHMS, selection_mode="multi", default=["reno", "cubic"],
                    format_func=D.ALGORITHM_LABELS.get, key="sens_algs")
    nseeds = c4.number_input("Seeds per point", 1, 10, 3, key="sens_seeds")
    dur = c5.number_input("Duration per run (s)", 1.0, 120.0, float(min(base.duration_s, 20.0)), key="sens_dur")
    try:
        values = parse_values(text, param)
        err = None
    except ValueError as exc:
        values, err = [], str(exc)
    total = len(values) * len(algs or []) * int(nseeds)
    if err:
        st.error(err)
    st.caption(f"{total} simulations (limit {MAX_RUNS}). Random loss only creates run-to-run variation when "
               f"loss probability > 0 or flows interact; otherwise every seed gives the same result.")
    if st.button("Run sweep", type="primary", disabled=bool(err) or not algs or total == 0 or total > MAX_RUNS):
        from dataclasses import replace
        bar = st.progress(0.0)
        try:
            df = run_sensitivity(replace(base, duration_s=float(dur)), param, values, list(algs),
                                 list(range(1, int(nseeds) + 1)),
                                 progress=lambda i, n: bar.progress(i / n, text=f"Run {i} of {n}"))
            st.session_state.sens = (param, df)
        except ValueError as exc:
            st.error(str(exc))
        bar.empty()
    if "sens" not in st.session_state:
        st.info("Choose a parameter and press **Run sweep**.")
        return
    param, df = st.session_state.sens
    label = SWEEPABLE[param][0] + (f" ({SWEEPABLE[param][1]})" if SWEEPABLE[param][1] else "")
    resp = st.segmented_control("Response", list(RESPONSES), default="goodput_mbps", format_func=RESPONSES.get,
                                key="sens_resp") or "goodput_mbps"
    summ = summarize(df, resp)
    st.plotly_chart(charts.sensitivity_chart(summ, label, RESPONSES[resp]), width="stretch")
    st.caption("Points are means over seeds; error bars are 95% confidence intervals (t-distribution). "
               "Hover for standard deviation, sample size and range.")
    st.dataframe(summ, hide_index=True, width="stretch")
    st.download_button("Download all runs (CSV)", table_csv(df), "sensitivity_runs.csv", "text/csv")
