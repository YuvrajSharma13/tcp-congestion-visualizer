"""Page 2 - Simulation Lab: configure, run, inspect."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics.explain import explain_event
from analytics.scenarios import SCENARIOS
from config.validation import make_config
from simulator.metrics import flow_metrics_frame
from ui import state
from ui.components import bdp_panel, config_editor, describe, hero, load_into_editor, metric_kpis, show_errors
from visualization import charts
from visualization.charts import TIMELINE_EVENTS

KEY = "lab"


def _presets() -> dict[str, object]:
    out = {}
    for sc in SCENARIOS:
        label, cfg = sc.build("reno")[0]
        out[f"Scenario · {sc.title}"] = cfg
    s = state.store()
    if s is not None:
        try:
            for name in s.list_presets()["name"]:
                out[f"Saved · {name}"] = ("saved", name)
        except Exception as exc:
            st.warning(f"Saved presets unavailable: {exc}")
    return out


def render() -> None:
    hero("Simulate", "Simulation Lab",
         "Set the bottleneck, the flows and their algorithms, then run. The same configuration and seed always "
         "reproduce the same trace.")

    presets = _presets()
    p1, p2, p3 = st.columns([3, 1, 1])
    choice = p1.selectbox("Start from a preset", ["—"] + list(presets), key="lab_preset_choice")
    if p2.button("Load preset", disabled=choice == "—", width="stretch"):
        val = presets[choice]
        cfg = state.store().load_preset(val[1]) if isinstance(val, tuple) else val
        load_into_editor(KEY, cfg)
        st.session_state.lab_config = cfg
        st.rerun()
    if p3.button("Reset to defaults", width="stretch"):
        cfg = make_config("reno", duration_s=20, buffer_packets=35)
        load_into_editor(KEY, cfg)
        st.session_state.lab_config = cfg
        st.session_state.pop("lab_run", None)
        st.rerun()

    cfg, errs = config_editor(KEY, state.lab_config())
    if errs:
        show_errors(errs)
    else:
        st.session_state.lab_config = cfg
        bdp_panel(cfg)

    b1, b2, b3, b4 = st.columns([1.2, 1, 1, 2])
    run = b1.button("Run simulation", type="primary", disabled=cfg is None, width="stretch")
    last = state.get_record(st.session_state.get("lab_run", ""))
    replay = b2.button("Replay last run", width="stretch",
                       help="Re-runs the last configuration from scratch (bypassing the cache) and checks the "
                            "trace is identical.")
    with b4.popover("Save as preset", disabled=cfg is None):
        name = st.text_input("Preset name", key="lab_preset_name")
        desc = st.text_input("Description", key="lab_preset_desc")
        if st.button("Save", key="lab_preset_save"):
            try:
                state.store().save_preset(name, cfg, desc)
                st.success(f"Saved preset '{name.strip()}'.")
            except Exception as exc:
                st.error(str(exc))
    st.session_state.persist_runs = b3.toggle("Save to history DB", value=st.session_state.get("persist_runs", True),
                                              help="Store configuration + metrics in data/experiments.db")

    if run and cfg is not None:
        est = cfg.bandwidth_bps * cfg.duration_s / (8 * cfg.mss_bytes)
        with st.status(f"Simulating ≈{est:,.0f} packets...", expanded=False) as s:
            res = state.simulate(cfg)
            rec = state.record_run(cfg, res, describe(cfg), "lab")
            st.session_state.lab_run = rec.run_id
            s.update(label=f"Done: {res.run_info['events_processed']:,} events in "
                           f"{res.run_info['wall_time_s']:.2f} s ({res.run_info['termination'].replace('_', ' ')})",
                     state="complete")
        last = rec
    if replay and last is None:
        st.info("Nothing to replay yet - run a simulation first.")
    if replay and last is not None and last.result is not None:
        from simulator.engine import run_simulation
        with st.spinner("Re-running from scratch..."):
            fresh = run_simulation(last.config)
        same = fresh.events.equals(last.result.events) and fresh.cwnd.equals(last.result.cwnd)
        (st.success if same else st.error)(
            "Replay reproduced the identical event trace and cwnd history (same configuration + seed)." if same
            else "Replay differed from the stored run - please report this as a bug.")

    if last is None or last.result is None:
        st.info("Configure the network above and press **Run simulation**. Results appear here.")
        return
    _results(last)


def _results(rec) -> None:
    res, m, cfg = rec.result, rec.metrics, rec.config
    st.divider()
    st.markdown(f"#### Results · run `{rec.run_id}`")
    st.caption("Configuration used: " + describe(cfg))
    metric_kpis(m, cfg)

    tabs = st.tabs(["cwnd & ssthresh", "RTT", "Throughput", "Queue", "Loss & retransmissions", "Event timeline",
                    "Per-flow"])
    with tabs[0]:
        o1, o2, o3, o4 = st.columns(4)
        clip = o1.checkbox("Clip inflation", value=True, help="Hide fast-recovery window-inflation spikes")
        ev = o2.checkbox("Mark events", value=True)
        ph = o3.checkbox("Shade phases", value=True, disabled=cfg.n_flows > 1)
        flows = list(range(cfg.n_flows))
        if cfg.n_flows > 1:
            flows = o4.multiselect("Flows", flows, default=flows, format_func=lambda f: f"Flow {f}")
        fig, note = charts.cwnd_chart(res, flows, clip_inflation=clip, mark_events=ev, shade_phases=ph)
        st.plotly_chart(fig, width="stretch")
        if note:
            st.caption(note)
        st.caption("Solid: cwnd; dotted: ssthresh. Shading (single flow): blue = slow start, pink = fast recovery; "
                   "unshaded = congestion avoidance. Phases come straight from the algorithm state.")
        st.plotly_chart(charts.ssthresh_chart(res), width="stretch")
    with tabs[1]:
        st.plotly_chart(charts.rtt_chart(res), width="stretch")
        st.caption("One sample per ACK whose segment was not retransmitted (Karn). RTT above the dashed base RTT is "
                   "queueing delay.")
    with tabs[2]:
        st.plotly_chart(charts.throughput_chart(res), width="stretch")
        st.caption("Goodput = unique in-order data delivered to the application; retransmissions do not count.")
    with tabs[3]:
        st.plotly_chart(charts.queue_chart(res), width="stretch")
    with tabs[4]:
        st.plotly_chart(charts.loss_chart(res), width="stretch")
        dt = m.drops_by_type
        st.caption(f"Drops by cause - overflow {dt['overflow']}, random {dt['random']}, burst {dt['burst']}, "
                   f"scripted {dt['forced']}. Retransmissions: {m.retx_packets}.")
    with tabs[5]:
        st.plotly_chart(charts.event_timeline(res), width="stretch")
        ev = res.events[res.events["event"].isin(TIMELINE_EVENTS)].reset_index(drop=True)
        if ev.empty:
            st.caption("No congestion events in this run.")
        else:
            st.markdown("**Inspect an event** - explanations are generated by rules from the logged values.")
            kinds = st.multiselect("Event types", sorted(ev["event"].unique()),
                                   default=[k for k in ("fast_retransmit", "timeout", "partial_ack", "drop")
                                            if k in set(ev["event"])], key="lab_ev_kinds")
            sub = ev[ev["event"].isin(kinds)].reset_index(drop=True) if kinds else ev
            if sub.empty:
                st.caption("No events of the selected types.")
            else:
                sel = st.dataframe(sub[["t", "event", "flow", "seq", "info", "cwnd", "ssthresh", "queue"]],
                                   hide_index=True, width="stretch", height=260, on_select="rerun",
                                   selection_mode="single-row", key="lab_ev_table",
                                   column_config={"t": st.column_config.NumberColumn(format="%.4f"),
                                                  "cwnd": st.column_config.NumberColumn(format="%.2f"),
                                                  "ssthresh": st.column_config.NumberColumn(format="%.2f")})
                rows = sel.selection.rows if sel and sel.selection else []
                row = sub.iloc[rows[0]] if rows else sub.iloc[0]
                st.markdown(f"<div class='tv-explain'><b>t = {row['t']:.4f} s · {row['event']}</b><br>"
                            f"{explain_event(res, row)}</div>", unsafe_allow_html=True)
    with tabs[6]:
        pf = flow_metrics_frame(m)
        st.dataframe(pf.drop(columns=["start_time_s"]), hide_index=True, width="stretch")
        if cfg.n_flows > 1:
            st.plotly_chart(charts.per_flow_bars(m), width="stretch")
            st.caption(f"Jain's fairness index = {m.jain_index:.3f}. It measures how equal the shares are, "
                       "not how well the link is used.")
    _ = pd
