"""Deterministic, rule-based explanations of logged simulator events.

Every explanation is built only from the event row itself, the configuration
and the cwnd/ssthresh values recorded just before and after the event.  No
language model is involved and nothing is invented: if a rule does not apply,
the generic description of the event type is returned.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from config import defaults as D
from simulator.trace import SimulationResult

GENERIC = {
    "flow_start": "The flow starts sending with its initial congestion window.",
    "send": "The sender hands a segment to the bottleneck.",
    "enqueue": "The segment reaches the bottleneck router.",
    "tx_start": "The bottleneck starts serialising this packet onto the link.",
    "tx_end": "The packet has been fully serialised and now propagates to the receiver.",
    "rx": "The receiver gets a segment and immediately returns a cumulative ACK.",
    "ack_rx": "An ACK reaches the sender.",
    "drop": "A packet was dropped.",
    "fast_retransmit": "Three duplicate ACKs triggered a fast retransmit.",
    "enter_recovery": "The sender entered fast recovery.",
    "exit_recovery": "The sender left fast recovery.",
    "partial_ack": "A partial ACK arrived during fast recovery.",
    "timeout": "The retransmission timer expired.",
    "cwnd_reset": "The congestion window was reset.",
    "phase_change": "The sender changed congestion-control phase.",
}

_PHASE_NAMES = {"slow_start": "slow start", "congestion_avoidance": "congestion avoidance",
                "fast_recovery": "fast recovery"}


def _state_before(result: SimulationResult, flow: int, t: float) -> tuple[float, float] | None:
    cw = result.cwnd
    sub = cw[(cw["flow"] == flow) & (cw["t"] < t)]
    if sub.empty:
        return None
    r = sub.iloc[-1]
    return float(r["cwnd"]), float(r["ssthresh"])


def explain_event(result: SimulationResult, row: pd.Series | dict[str, Any]) -> str:
    cfg = result.config
    ev = row["event"]
    flow = int(row["flow"])
    seq = int(row["seq"])
    info = str(row["info"])
    t = float(row["t"])
    cwnd, ssthresh = row.get("cwnd"), row.get("ssthresh")
    alg = cfg.flows[flow].algorithm if 0 <= flow < cfg.n_flows else "cross"
    alg_label = D.ALGORITHM_LABELS.get(alg, alg)
    who = f"flow {flow} ({alg_label})" if flow >= 0 else "cross traffic"

    if ev == "drop":
        if info.startswith("overflow"):
            return (f"Buffer overflow: a packet of {who} (segment {seq}) arrived while the bottleneck buffer "
                    f"already held {cfg.buffer_packets}/{cfg.buffer_packets} waiting packets, so drop-tail "
                    f"discarded it. This is congestion loss: the senders together are pushing more than the "
                    f"link ({cfg.bandwidth_mbps:g} Mbps) can drain. The sender will only find out from "
                    f"duplicate ACKs (about one RTT later) or, failing that, from a retransmission timeout.")
        if info == "random":
            return (f"Random link loss: segment {seq} of {who} was lost on the wire after being transmitted, "
                    f"drawn with probability {cfg.loss_prob:.4g}. It is not caused by congestion, but TCP "
                    f"cannot tell the difference, so it will still reduce its window.")
        if info == "burst":
            return (f"Burst loss: segment {seq} of {who} finished transmission inside a configured loss burst, "
                    f"so it was lost. Several consecutive losses like this often leave too few packets in flight "
                    f"to generate three duplicate ACKs, which forces a retransmission timeout.")
        if info == "forced":
            return (f"Scripted loss: the scenario drops the first transmission of segment {seq} of {who} to "
                    f"show how the algorithm recovers.")
    if ev == "fast_retransmit":
        before = _state_before(result, flow, t)
        b = f" Before the loss cwnd was {before[0]:.1f} segments." if before else ""
        rule = {
            "tahoe": "Tahoe sets ssthresh to half of FlightSize, drops cwnd to 1 segment and restarts slow start "
                     "(it has no fast recovery).",
            "reno": "Reno sets ssthresh to half of FlightSize and enters fast recovery with cwnd = ssthresh + 3.",
            "newreno": "NewReno sets ssthresh to half of FlightSize, records 'recover' (the highest segment sent) "
                       "and enters fast recovery with cwnd = ssthresh + 3.",
            "cubic": f"CUBIC remembers W_max, sets ssthresh = {cfg.cubic_beta:g} x FlightSize "
                     f"(multiplicative decrease with beta = {cfg.cubic_beta:g}) and enters fast recovery.",
        }.get(alg, "")
        return (f"Fast retransmit: {who} received three duplicate ACKs all asking for segment {seq}. Later "
                f"segments were arriving, so segment {seq} was very likely lost rather than delayed, and it is "
                f"retransmitted immediately instead of waiting for the RTO.{b} {rule} "
                f"After the response: cwnd = {float(cwnd):.1f}, ssthresh = {float(ssthresh):.1f}.")
    if ev == "enter_recovery":
        return (f"{who} is now in fast recovery ({info}). Each further duplicate ACK means another segment has "
                f"left the network, so cwnd is inflated by one segment per duplicate ACK to keep data flowing.")
    if ev == "partial_ack":
        return (f"Partial ACK: the cumulative ACK moved forward but not past 'recover', which proves that another "
                f"segment from the same window was lost. NewReno-style recovery retransmits segment {seq} "
                f"immediately and stays in fast recovery instead of waiting for three more duplicate ACKs. "
                f"({info})")
    if ev == "exit_recovery":
        if "partial" in info:
            return (f"{who} left fast recovery on a partial ACK. Classic Reno exits on the first new ACK, so a "
                    f"second loss from the same window must be detected again by duplicate ACKs or by a timeout. "
                    f"({info})")
        return f"Fast recovery is over for {who}: {info}. Congestion avoidance resumes."
    if ev == "timeout":
        m = re.search(r"RTO=(\d+) ms", info)
        rto = f"{m.group(1)} ms" if m else "the RTO"
        return (f"Retransmission timeout: no ACK advanced the window of {who} for {rto}, so segment {seq} is "
                f"presumed lost. This happens when too few segments are in flight to produce three duplicate "
                f"ACKs (for example after a burst of losses, or when a retransmission is itself lost). "
                f"The response is the most severe one: ssthresh is reduced, cwnd drops to 1 segment, the RTO "
                f"doubles (exponential back-off, RFC 6298) and the sender resends from segment {seq}.")
    if ev == "cwnd_reset":
        return f"Window reduction for {who}: {info}."
    if ev == "phase_change":
        a, _, b = info.partition("->")
        an, bn = _PHASE_NAMES.get(a, a), _PHASE_NAMES.get(b, b)
        if a == "slow_start" and b == "congestion_avoidance":
            return (f"{who} switched from slow start to congestion avoidance because cwnd ({float(cwnd):.1f}) "
                    f"reached ssthresh ({float(ssthresh):.1f}). Growth slows from doubling every RTT to "
                    + ("the cubic function of time since the last reduction." if alg == "cubic"
                       else "about one segment per RTT (additive increase)."))
        return f"{who} moved from {an} to {bn}."
    if ev == "send" and info != "new":
        kinds = {
            "fast_retx": "a fast retransmission triggered by three duplicate ACKs",
            "partial_retx": "a retransmission triggered by a partial ACK during fast recovery",
            "rto_retx": "a retransmission after a timeout",
            "gbn_retx": "a go-back-N retransmission: after a timeout (or Tahoe's fast retransmit) the sender "
                        "resends from the first unacknowledged segment, so the receiver may already hold this one",
        }
        return f"Segment {seq} of {who} is sent again: {kinds.get(info, info)}."
    if ev == "rx":
        if info.startswith("out_of_order"):
            return (f"Segment {seq} arrived out of order: an earlier segment is missing, so the receiver buffers "
                    f"it and repeats its previous cumulative ACK ({info.split('ACK ')[-1]}). That repeated ACK is "
                    f"a duplicate ACK at the sender.")
        if info.startswith("duplicate"):
            return f"Segment {seq} had already been received; the copy is discarded and an ACK is still sent."
        return f"Segment {seq} arrived in order and was delivered to the application; {info.split('; ')[-1]}."
    if ev == "ack_rx":
        if info.startswith("dup"):
            n = info.replace("dup#", "")
            return (f"Duplicate ACK #{n} for segment {seq}: the receiver is still waiting for segment {seq}. "
                    + ("A third duplicate ACK triggers fast retransmit." if n in {"1", "2"} else ""))
        if info == "new":
            return f"New ACK: everything before segment {seq} is acknowledged, so the window slides forward."
    if ev == "enqueue" and info == "queued":
        return (f"The link is busy, so the packet waits in the FIFO buffer (now {int(row.get('queue', 0))} "
                f"packets). Each waiting packet adds {cfg.tx_time_s * 1000:.2f} ms of queueing delay.")
    return GENERIC.get(ev, ev)
