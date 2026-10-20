"""Session state, cached simulation runner and experiment history for the dashboard."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

import streamlit as st

from config.validation import SimulationConfig, make_config
from simulator.engine import run_simulation
from simulator.metrics import RunMetrics, compute_metrics
from simulator.trace import SimulationResult
from storage.experiment_store import ExperimentStore, make_run_id

MAX_SESSION_RESULTS = 12


@dataclass
class RunRecord:
    run_id: str
    label: str
    source: str
    created: str
    config: SimulationConfig
    metrics: RunMetrics
    result: SimulationResult | None
    extras: dict[str, Any] = field(default_factory=dict)


@st.cache_resource(max_entries=24, show_spinner=False)
def _cached_run(config_json: str) -> SimulationResult:
    # Key = the full JSON of the configuration, including seed and every parameter.
    return run_simulation(SimulationConfig.from_json(config_json))


def simulate(cfg: SimulationConfig) -> SimulationResult:
    """Run (or reuse) a simulation.  Results are immutable; never modify the returned object."""
    cfg.ensure_valid()
    return _cached_run(cfg.to_json())


def store() -> ExperimentStore | None:
    if "store" not in st.session_state:
        try:
            st.session_state.store = ExperimentStore()
            st.session_state.store_error = None
        except Exception as exc:  # e.g. read-only folder
            st.session_state.store = None
            st.session_state.store_error = f"{type(exc).__name__}: {exc}"
    return st.session_state.store


def history() -> list[RunRecord]:
    return st.session_state.setdefault("history", [])


def record_run(cfg: SimulationConfig, result: SimulationResult, label: str, source: str,
               persist: bool | None = None, **extras) -> RunRecord:
    m = compute_metrics(result)
    rec = RunRecord(make_run_id(cfg), label, source, _dt.datetime.now().strftime("%H:%M:%S"), cfg, m, result, extras)
    h = history()
    h.append(rec)
    # keep full traces only for recent runs (memory); metrics stay for all
    for old in h[:-MAX_SESSION_RESULTS]:
        old.result = None
    st.session_state.total_runs = st.session_state.get("total_runs", 0) + 1
    if persist is None:
        persist = st.session_state.get("persist_runs", True)
    s = store()
    if persist and s is not None:
        try:
            s.save_run(rec.run_id, cfg, m.to_dict(), label=f"{source}: {label}")
        except Exception as exc:
            st.session_state.store_error = f"{type(exc).__name__}: {exc}"
    return rec


def latest(source: str | None = None) -> RunRecord | None:
    for r in reversed(history()):
        if (source is None or r.source == source) and r.result is not None:
            return r
    return None


def get_record(run_id: str) -> RunRecord | None:
    for r in history():
        if r.run_id == run_id:
            return r
    return None


def lab_config() -> SimulationConfig:
    if "lab_config" not in st.session_state:
        st.session_state.lab_config = make_config("reno", duration_s=20, buffer_packets=35)
    return st.session_state.lab_config
