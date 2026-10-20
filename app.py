"""TCP Congestion Control Visualizer - Streamlit entry point.

Run from the project folder:   python -m streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from ui.components import inject_css  # noqa: E402
from ui.views import (comparison, experiments, learning, ml_lab, overview, playback, scenarios,  # noqa: E402
                      sensitivity, simulation_lab, validation_page)

st.set_page_config(page_title="TCP Congestion Control Visualizer", page_icon="📶", layout="wide",
                   initial_sidebar_state="expanded")
inject_css()

pages = {
    "Simulate": [
        st.Page(overview.render, title="Overview", icon=":material/dashboard:", url_path="overview", default=True),
        st.Page(simulation_lab.render, title="Simulation Lab", icon=":material/science:", url_path="lab"),
        st.Page(playback.render, title="Packet Visualizer", icon=":material/animation:", url_path="packets"),
    ],
    "Analyse": [
        st.Page(comparison.render, title="Algorithm Comparison", icon=":material/compare_arrows:", url_path="compare"),
        st.Page(scenarios.render, title="Scenario Lab", icon=":material/route:", url_path="scenarios"),
        st.Page(sensitivity.render, title="Sensitivity Analysis", icon=":material/tune:", url_path="sensitivity"),
        st.Page(experiments.render, title="Experiments & Reports", icon=":material/description:", url_path="reports"),
    ],
    "Learn & research": [
        st.Page(learning.render, title="Learning Centre", icon=":material/school:", url_path="learn"),
        st.Page(ml_lab.render, title="AI Congestion Prediction", icon=":material/psychology:", url_path="ai"),
        st.Page(validation_page.render, title="Validation", icon=":material/verified:", url_path="validation"),
    ],
}

nav = st.navigation(pages)
with st.sidebar:
    st.caption("Segment-level discrete-event model of TCP Tahoe, Reno, NewReno and CUBIC "
               "(RFC 5681, 6582, 6298, 9438). Every chart is drawn from the simulator's own event trace.")
    runs = st.session_state.get("total_runs", 0)
    st.caption(f"Simulations this session: **{runs}**")
nav.run()
