"""Reconstruct network state at any instant from the recorded event log.

Every packet's position is derived from logged events only:

* waiting in the buffer : enqueue time <= t < tx_start
* being serialised      : tx_start <= t < tx_end
* propagating           : tx_end <= t < rx (position = elapsed / propagation delay)
* lost on the link      : tx_end <= t < drop time (a link loss is logged at tx_end)
* ACK in flight         : rx <= t < ack_rx (ACK path has propagation delay only)

Requires a run with ``record_packet_events=True``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from simulator.trace import SimulationResult

PLAYBACK_EVENTS = ["flow_start", "send", "enqueue", "tx_start", "tx_end", "drop", "rx", "ack_rx", "fast_retransmit",
                   "enter_recovery", "partial_ack", "exit_recovery", "timeout", "cwnd_reset", "phase_change"]


class PlaybackUnavailable(ValueError):
    pass


@dataclass
class Journeys:
    data: pd.DataFrame   # one row per transmission uid
    acks: pd.DataFrame   # one row per ACK: flow, ack, t_send, t_arrive, trigger uid
    delay: float


def build_journeys(result: SimulationResult) -> Journeys:
    if not result.config.record_packet_events:
        raise PlaybackUnavailable("This run was made without per-packet events. Re-run it with "
                                  "'Record per-packet events' enabled to use the packet visualizer.")
    ev = result.events
    pk = ev[ev["uid"] >= 0]
    piv = {}
    for name in ("send", "enqueue", "tx_start", "tx_end", "rx", "drop"):
        s = pk[pk["event"] == name].drop_duplicates("uid").set_index("uid")
        piv[name] = s
    base = pd.concat([piv["send"][["flow", "seq", "t", "info"]].rename(columns={"t": "t_send", "info": "kind"}),
                      piv["enqueue"][["flow", "seq"]].iloc[0:0]], axis=0)
    # cross-traffic packets have no 'send' event; take them from enqueue/drop
    others = pd.concat([piv["enqueue"][["flow", "seq", "t"]], piv["drop"][["flow", "seq", "t"]]])
    others = others[~others.index.isin(base.index)]
    others = others[~others.index.duplicated()]
    if len(others):
        extra = others.rename(columns={"t": "t_send"})
        extra["kind"] = np.where(extra["flow"] < 0, "cross", "new")
        base = pd.concat([base, extra])
    d = base.copy()
    d["t_enqueue"] = piv["enqueue"]["t"].reindex(d.index)
    d["t_tx_start"] = piv["tx_start"]["t"].reindex(d.index)
    d["t_tx_end"] = piv["tx_end"]["t"].reindex(d.index)
    d["t_rx"] = piv["rx"]["t"].reindex(d.index)
    d["t_drop"] = piv["drop"]["t"].reindex(d.index)
    d["drop_cause"] = piv["drop"]["info"].reindex(d.index).str.split(":").str[0]
    d = d.reset_index().rename(columns={"index": "uid"}).sort_values("t_send").reset_index(drop=True)

    rx = pk[pk["event"] == "rx"].copy()
    rx["ack"] = rx["info"].str.extract(r"ACK (\d+)")[0].astype(float)
    delay = result.config.one_way_delay_s
    acks = pd.DataFrame({"flow": rx["flow"].to_numpy(), "ack": rx["ack"].to_numpy(), "uid": rx["uid"].to_numpy(),
                         "t_send": rx["t"].to_numpy(), "t_arrive": rx["t"].to_numpy() + delay})
    return Journeys(d, acks, delay)


def state_at(j: Journeys, t: float, recent_s: float) -> dict:
    d = j.data
    queued = d[(d["t_enqueue"] <= t) & ((d["t_tx_start"] > t) | d["t_tx_start"].isna())]
    queued = queued.sort_values("t_enqueue")
    service = d[(d["t_tx_start"] <= t) & (d["t_tx_end"] > t)]
    prop_end = d["t_rx"].fillna(d["t_drop"])
    fly = d[(d["t_tx_end"] <= t) & (prop_end > t) & (d["flow"] >= 0)].copy()
    if j.delay > 0:
        fly["pos"] = ((t - fly["t_tx_end"]) / j.delay).clip(0, 1)
    else:
        fly["pos"] = 1.0
    a = j.acks
    acks = a[(a["t_send"] <= t) & (a["t_arrive"] > t)].copy()
    acks["pos"] = ((t - acks["t_send"]) / j.delay).clip(0, 1) if j.delay > 0 else 1.0
    drops = d[(d["t_drop"] <= t) & (d["t_drop"] > t - recent_s)]
    return {"queued": queued, "service": service, "fly": fly, "acks": acks, "drops": drops}


def playback_steps(result: SimulationResult, t0: float, max_events: int) -> pd.DataFrame:
    ev = result.events
    s = ev[(ev["t"] >= t0) & ev["event"].isin(PLAYBACK_EVENTS)]
    return s.head(max_events).reset_index().rename(columns={"index": "row"})


def cc_state_at(result: SimulationResult, t: float) -> pd.DataFrame:
    cw = result.cwnd[result.cwnd["t"] <= t]
    if cw.empty:
        return pd.DataFrame(columns=["flow", "cwnd", "ssthresh", "phase"])
    return cw.groupby("flow").tail(1)[["flow", "cwnd", "ssthresh", "phase"]].reset_index(drop=True)
