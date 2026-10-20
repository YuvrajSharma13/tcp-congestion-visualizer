"""Page 3 - Live-style packet visualizer (playback of a recorded trace)."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from analytics.explain import explain_event
from config import defaults as D
from config.validation import ForcedDrop, make_config
from ui import state
from ui.components import describe, hero
from visualization.charts import decimate_step
from visualization.playback import PlaybackUnavailable, build_journeys, cc_state_at, playback_steps, state_at
from visualization.theme import STATUS, TEMPLATE, TEXT_2, flow_color

SPEEDS = {"1 event/s": 1.0, "2 events/s": 0.5, "5 events/s": 0.2, "10 events/s": 0.1, "20 events/s": 0.05}
MAX_STEPS = 2000
DEMO = make_config("newreno", duration_s=4, bandwidth_mbps=5, delay_ms=15, buffer_packets=10, initial_ssthresh=24,
                   forced_drops=(ForcedDrop(0, 120), ForcedDrop(0, 123)))


@st.cache_resource(max_entries=6, show_spinner=False)
def _journeys(run_id: str, _res):
    return build_journeys(_res)


def render() -> None:
    hero("Simulate", "Packet Visualizer",
         "Step through a finished simulation event by event. Packet positions, queue contents, drops and the "
         "sender's cwnd/ssthresh are reconstructed from the logged events - nothing is decorative.")

    candidates = [r for r in reversed(state.history()) if r.result is not None and r.config.record_packet_events]
    c1, c2 = st.columns([3, 1])
    labels = {r.run_id: f"{r.run_id} · {r.source} · {describe(r.config)[:80]}" for r in candidates}
    run_id = c1.selectbox("Trace to play back", list(labels), format_func=labels.get, key="pb_run") if labels else None
    if c2.button("Load demo trace", width="stretch",
                 help="NewReno, 5 Mbps, 10-packet buffer, two scripted losses in one window"):
        res = state.simulate(DEMO)
        rec = state.record_run(DEMO, res, "packet playback demo", "playback")
        st.session_state.pb_run = rec.run_id
        st.session_state.pb_idx = 0
        st.rerun()
    if run_id is None:
        st.info("No run with per-packet events yet. Load the demo trace, or run a simulation in the Simulation Lab "
                "with *Record per-packet events* enabled (Advanced).")
        return
    rec = state.get_record(run_id)
    res = rec.result
    try:
        j = _journeys(run_id, res)
    except PlaybackUnavailable as exc:
        st.warning(str(exc))
        return

    w1, w2 = st.columns([3, 1])
    t0 = w1.slider("Start playback at (s)", 0.0, float(res.duration_s), 0.0, step=0.05, key="pb_t0")
    focus = w2.selectbox("Jump to", ["—", "first drop", "first fast retransmit", "first timeout", "first partial ACK"],
                         key="pb_focus")
    if focus != "—":
        name = {"first drop": "drop", "first fast retransmit": "fast_retransmit", "first timeout": "timeout",
                "first partial ACK": "partial_ack"}[focus]
        hit = res.events[res.events["event"] == name]
        if hit.empty:
            st.caption(f"No {name.replace('_', ' ')} in this run.")
        else:
            t0 = max(float(hit["t"].iloc[0]) - 0.15, 0.0)
    steps = playback_steps(res, t0, MAX_STEPS)
    if steps.empty:
        st.warning("No events after this time.")
        return
    key = (run_id, round(t0, 4))
    if st.session_state.get("pb_key") != key:
        st.session_state.pb_key = key
        st.session_state.pb_idx = 0
        st.session_state.pb_playing = False

    k1, k2, k3, k4, k5 = st.columns([1, 1, 1, 1, 2])
    if k1.button("⏮ Reset", width="stretch"):
        st.session_state.pb_idx = 0
        st.session_state.pb_playing = False
    if k2.button("◀ Step", width="stretch"):
        st.session_state.pb_idx = max(st.session_state.pb_idx - 1, 0)
        st.session_state.pb_playing = False
    playing = st.session_state.get("pb_playing", False)
    if k3.button("⏸ Pause" if playing else "▶ Play", width="stretch", type="primary"):
        st.session_state.pb_playing = not playing
        st.rerun()
    if k4.button("Step ▶", width="stretch"):
        st.session_state.pb_idx = min(st.session_state.pb_idx + 1, len(steps) - 1)
        st.session_state.pb_playing = False
    speed = k5.select_slider("Speed", list(SPEEDS), value=st.session_state.get("pb_speed", "5 events/s"),
                             key="pb_speed")
    only_cc = st.toggle("Step only through congestion events (drops, retransmissions, recovery, timeouts)",
                        key="pb_only_cc")

    interval = SPEEDS[speed] if st.session_state.get("pb_playing") else None

    @st.fragment(run_every=interval)
    def player():
        idx = st.session_state.get("pb_idx", 0)
        if st.session_state.get("pb_playing"):
            nxt = idx + 1
            if only_cc:
                cc_mask = ~steps["event"].isin(["send", "enqueue", "tx_start", "tx_end", "rx", "ack_rx"]) | \
                    ((steps["event"] == "send") & (steps["info"] != "new"))
                later = steps.index[(steps.index > idx) & cc_mask]
                nxt = int(later[0]) if len(later) else len(steps) - 1
            if nxt >= len(steps):
                nxt = len(steps) - 1
                st.session_state.pb_playing = False
            st.session_state.pb_idx = idx = nxt
        row = steps.iloc[idx]
        t = float(row["t"])
        st.progress((idx + 1) / len(steps), text=f"Event {idx + 1} of {len(steps)} · t = {t:.5f} s")
        from visualization.topology import topology_figure
        snap = state_at(j, t, recent_s=max(res.config.tx_time_s * 3, 0.002))
        left, right = st.columns([2.2, 1])
        with left:
            st.plotly_chart(topology_figure(res.config, snap, height=380), width="stretch",
                            config={"displayModeBar": False}, key=f"topo_{idx}")
            st.caption("Filled squares: data packets (colour = flow); hollow: retransmissions; triangles: ACKs on the "
                       "return path; ✕: a drop in the last few transmission times.")
        with right:
            st.markdown(f"**Event:** `{row['event']}` · flow {int(row['flow'])}"
                        + (f" · seg {int(row['seq'])}" if row["seq"] >= 0 else ""))
            st.markdown(f"<div class='tv-explain'>{explain_event(res, row)}</div>", unsafe_allow_html=True)
            ccs = cc_state_at(res, t)
            st.markdown("**Sender state at this instant**")
            for _, s in ccs.iterrows():
                st.markdown(f"<span style='color:{flow_color(int(s['flow']))}'>■</span> Flow {int(s['flow'])} "
                            f"({D.ALGORITHM_LABELS[res.config.flows[int(s['flow'])].algorithm]}): "
                            f"cwnd **{s['cwnd']:.2f}**, ssthresh **{s['ssthresh']:.2f}**, "
                            f"{s['phase'].replace('_', ' ')}", unsafe_allow_html=True)
            st.markdown(f"Queue **{len(snap['queued'])}/{res.config.buffer_packets}** · "
                        f"{len(snap['fly'])} data packets and {len(snap['acks'])} ACKs in flight")
        _mini_cwnd(res, t, idx)

    player()
    def _scrub():
        st.session_state.pb_idx = st.session_state.pb_scrub
        st.session_state.pb_playing = False

    st.slider("Scrub", 0, len(steps) - 1, value=min(st.session_state.get("pb_idx", 0), len(steps) - 1),
              key="pb_scrub", on_change=_scrub, help="Drag to jump to any event in the window")
    with st.expander("Events in this playback window"):
        st.dataframe(steps[["t", "event", "flow", "seq", "info", "cwnd", "ssthresh", "queue"]], hide_index=True,
                     height=300, width="stretch")


def _mini_cwnd(res, t, idx):
    fig = go.Figure()
    fig.update_layout(template=TEMPLATE, height=200, margin=dict(l=50, r=10, t=10, b=30), showlegend=False,
                      xaxis_title=None, yaxis_title="cwnd")
    for f in range(res.config.n_flows):
        c = res.cwnd[res.cwnd["flow"] == f]
        x, y = decimate_step(c["t"].to_numpy(), c["cwnd"].to_numpy(), 3000)
        fig.add_trace(go.Scattergl(x=x, y=y, mode="lines", line=dict(color=flow_color(f), width=1.6, shape="hv")))
    fig.add_vline(x=t, line=dict(color=STATUS["timeout"], width=1.5))
    lo, hi = max(t - 2.0, 0), min(t + 2.0, res.duration_s)
    fig.update_xaxes(range=[lo, hi], color=TEXT_2)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key=f"mini_{idx}")
