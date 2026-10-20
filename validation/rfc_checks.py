"""Standards-based validation of algorithm state transitions.

Two kinds of checks:

1. **Rule probes** drive each algorithm object directly with a scripted
   sequence of ACKs and compare the resulting cwnd/ssthresh with the rule
   stated in the RFC.  They are independent of the network model.
2. **Trace audits** inspect a finished simulation and verify invariants and
   per-event transitions (e.g. "cwnd = ssthresh + 3 on entering Reno fast
   recovery", "cwnd = 1 after every timeout", "queue never exceeds the buffer").

Both return ``CheckResult`` rows that the dashboard turns into a validation
report.  Passing these checks shows the simulator follows the *modelled*
rules; it does not make the simulator a complete TCP implementation (see
``LIMITATIONS``).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from algorithms import create_algorithm
from algorithms.base import AckInfo
from algorithms.cubic import CubicCC
from simulator.trace import SimulationResult

PASS, FAIL, NA = "pass", "fail", "not applicable"


@dataclass
class CheckResult:
    check: str
    reference: str
    status: str
    detail: str


def _ai(ack=0, newly=0, flight=10, snd_max=None, now=0.0, srtt=0.1, loss_flight=None) -> AckInfo:
    return AckInfo(now=now, ack=ack, newly_acked=newly, flight_size=flight,
                   loss_flight=flight if loss_flight is None else loss_flight,
                   snd_max=ack + flight if snd_max is None else snd_max, srtt=srtt, min_rtt=srtt)


def _r(name, ref, ok, detail) -> CheckResult:
    return CheckResult(name, ref, PASS if ok else FAIL, detail)


# ----------------------------------------------------------------- rule probes
def rule_probes() -> list[CheckResult]:
    out: list[CheckResult] = []
    for alg in ("tahoe", "reno", "newreno", "cubic"):
        cc = create_algorithm(alg, 1, 8)
        for i in range(4):
            cc.on_new_ack(_ai(ack=i + 1, newly=1))
        out.append(_r(f"{alg}: slow start adds 1 segment per new ACK", "RFC 5681 §3.1",
                      cc.cwnd == 5.0, f"cwnd after 4 ACKs from 1 = {cc.cwnd}"))
        cc = create_algorithm(alg, 1, 64)
        cc.on_timeout(_ai(ack=10, flight=40, snd_max=50))
        exp_ss = 0.7 * 40 if alg == "cubic" else 20.0
        out.append(_r(f"{alg}: timeout sets cwnd = 1 and reduces ssthresh",
                      "RFC 9438 §4.8" if alg == "cubic" else "RFC 5681 §3.1 eq. 4",
                      cc.cwnd == 1.0 and math.isclose(cc.ssthresh, exp_ss),
                      f"cwnd = {cc.cwnd}, ssthresh = {cc.ssthresh} (expected {exp_ss})"))

    for alg in ("reno", "newreno"):
        cc = create_algorithm(alg, 1, 20)
        cc.cwnd = 20.0
        cc.on_new_ack(_ai(ack=1, newly=1))
        out.append(_r(f"{alg}: congestion avoidance adds 1/cwnd per ACK", "RFC 5681 §3.1 eq. 3",
                      math.isclose(cc.cwnd, 20.05), f"cwnd 20 -> {cc.cwnd:.4f}"))
        cc = create_algorithm(alg, 30, 64)
        r = [cc.on_dupack(_ai(ack=100, flight=30, snd_max=130), n) for n in (1, 2, 3)]
        out.append(_r(f"{alg}: 3rd duplicate ACK -> fast retransmit, ssthresh = FlightSize/2, cwnd = ssthresh + 3",
                      "RFC 5681 §3.2 steps 2-3" if alg == "reno" else "RFC 6582 §3.2 step 2",
                      r[2].retransmit_head and not r[0].retransmit_head and cc.ssthresh == 15 and cc.cwnd == 18,
                      f"ssthresh = {cc.ssthresh}, cwnd = {cc.cwnd}"))
        cc.on_dupack(_ai(ack=100, flight=30, snd_max=130), 4)
        out.append(_r(f"{alg}: each further duplicate ACK inflates cwnd by 1", "RFC 5681 §3.2 step 4",
                      cc.cwnd == 19, f"cwnd = {cc.cwnd}"))

    cc = create_algorithm("tahoe", 30, 64)
    for n in (1, 2, 3):
        r = cc.on_dupack(_ai(ack=100, flight=30, snd_max=130), n)
    out.append(_r("tahoe: 3rd duplicate ACK -> fast retransmit, ssthresh = FlightSize/2, cwnd = 1 (no fast recovery)",
                  "Jacobson 1988; RFC 5681 §3.2 (fast retransmit only)",
                  r.go_back_n and cc.cwnd == 1 and cc.ssthresh == 15 and not cc.in_recovery,
                  f"cwnd = {cc.cwnd}, ssthresh = {cc.ssthresh}"))

    cc = create_algorithm("reno", 30, 64)
    cc.on_dupack(_ai(ack=100, flight=30, snd_max=130), 3)
    cc.on_new_ack(_ai(ack=110, newly=10, flight=20, snd_max=130))
    out.append(_r("reno: first new ACK ends fast recovery with cwnd = ssthresh", "RFC 5681 §3.2 step 6",
                  not cc.in_recovery and cc.cwnd == 15, f"in_recovery = {cc.in_recovery}, cwnd = {cc.cwnd}"))

    cc = create_algorithm("newreno", 30, 64)
    cc.on_dupack(_ai(ack=100, flight=30, snd_max=130), 3)          # recover = 129, cwnd = 18
    r = cc.on_new_ack(_ai(ack=110, newly=10, flight=20, snd_max=130))
    out.append(_r("newreno: partial ACK retransmits, deflates cwnd by newly-acked - 1, stays in recovery",
                  "RFC 6582 §3.2 step 5 (partial)",
                  r.retransmit_head and cc.in_recovery and cc.cwnd == 18 - 10 + 1,
                  f"retransmit = {r.retransmit_head}, cwnd = {cc.cwnd}"))
    cc.on_new_ack(_ai(ack=130, newly=20, flight=2, snd_max=132))
    out.append(_r("newreno: full ACK exits with cwnd = min(ssthresh, max(FlightSize,1)+1)",
                  "RFC 6582 §3.2 step 5 (full), option 1",
                  not cc.in_recovery and cc.cwnd == 3, f"cwnd = {cc.cwnd}"))
    cc = create_algorithm("newreno", 30, 64)
    cc.recover = 200
    r = cc.on_dupack(_ai(ack=150, flight=30, snd_max=180), 3)
    out.append(_r("newreno: no fast retransmit when the ACK does not cover 'recover'", "RFC 6582 §3.2 step 2",
                  not r.retransmit_head, f"retransmit = {r.retransmit_head}"))

    cc = CubicCC(100, 50)
    cc.on_dupack(_ai(ack=10, flight=100, snd_max=110), 3)
    out.append(_r("cubic: multiplicative decrease ssthresh = 0.7 x FlightSize, W_max = cwnd",
                  "RFC 9438 §4.6", math.isclose(cc.ssthresh, 70) and cc.w_max == 100,
                  f"ssthresh = {cc.ssthresh}, W_max = {cc.w_max}"))
    cc = CubicCC(100, 50)
    cc.w_max = 150
    cc.on_dupack(_ai(ack=10, flight=100, snd_max=110), 3)
    out.append(_r("cubic: fast convergence W_max = cwnd x (1 + beta) / 2", "RFC 9438 §4.7",
                  math.isclose(cc.w_max, 85.0), f"W_max = {cc.w_max}"))
    k = CubicCC.compute_k(100, 70, 0.4)
    out.append(_r("cubic: K = cbrt((W_max - cwnd_epoch)/C) and W_cubic(K) = W_max", "RFC 9438 §4.2 eqs. 1-2",
                  math.isclose(k, (30 / 0.4) ** (1 / 3)), f"K = {k:.4f} s"))
    cc = CubicCC(20, 20)
    cc.w_max, cc.cwnd_prior = 20.0, 20.0
    cc.on_new_ack(_ai(ack=1, newly=1, now=0.0))
    before = cc.cwnd
    cc.on_new_ack(_ai(ack=2, newly=1, now=50.0))
    out.append(_r("cubic: per-ACK target is clamped to 1.5 x cwnd", "RFC 9438 §4.2 (target bounds)",
                  math.isclose(cc.cwnd, before + 0.5), f"cwnd {before:.3f} -> {cc.cwnd:.3f}"))
    return out


# ------------------------------------------------------------------ trace audits
def audit_trace(result: SimulationResult) -> list[CheckResult]:
    cfg = result.config
    ev = result.events
    cw = result.cwnd
    out: list[CheckResult] = []

    q = result.queue["queue"]
    out.append(_r("Queue occupancy stays within [0, buffer]", "model invariant",
                  q.min() >= 0 and q.max() <= cfg.buffer_packets,
                  f"min {q.min()}, max {q.max()}, buffer {cfg.buffer_packets}"))
    out.append(_r("Event timestamps never decrease", "discrete-event engine",
                  bool(np.all(np.diff(ev["t"].to_numpy()) >= 0)), f"{len(ev):,} logged events"))
    out.append(_r("cwnd >= 1 and ssthresh >= 2 segments throughout", "RFC 5681 eq. 4 lower bound",
                  cw["cwnd"].min() >= 1 and cw["ssthresh"].min() >= 2,
                  f"min cwnd {cw['cwnd'].min():.2f}, min ssthresh {cw['ssthresh'].min():.2f}"))
    deliv = result.deliveries.groupby("flow")["segments"].sum().to_dict() if len(result.deliveries) else {}
    ok = all(deliv.get(s["flow"], 0) == s["delivered_segments"] <= s["snd_max"] for s in result.flow_stats)
    out.append(_r("Each segment is delivered to the application exactly once", "receiver model",
                  ok, ", ".join(f"flow {s['flow']}: {s['delivered_segments']} delivered / {s['snd_max']} sent"
                                for s in result.flow_stats)))

    to = ev[ev["event"] == "timeout"]
    if len(to):
        flights = to["info"].str.extract(r"flight=(\d+)")[0].astype(int)
        out.append(_r("Timeouts fire only while data is outstanding", "RFC 6298 §5.2",
                      bool((flights > 0).all()), f"{len(to)} timeouts"))
        bad = 0
        for _, row in to.iterrows():
            nxt = cw[(cw["flow"] == row["flow"]) & (cw["t"] >= row["t"])]
            if nxt.empty or nxt["cwnd"].iloc[0] != 1.0:
                bad += 1
        out.append(_r("cwnd = 1 segment immediately after every timeout", "RFC 5681 §3.1 (LW = 1 SMSS)",
                      bad == 0, f"{len(to) - bad}/{len(to)} timeouts followed by cwnd = 1"))
    else:
        out.append(CheckResult("Timeout transitions", "RFC 5681 / RFC 6298", NA, "no timeouts in this run"))

    algs = {i: f.algorithm for i, f in enumerate(cfg.flows)}
    enter = ev[ev["event"] == "enter_recovery"]
    if len(enter):
        ok = np.isclose(enter["cwnd"], enter["ssthresh"] + 3).all()
        out.append(_r("Entering fast recovery sets cwnd = ssthresh + 3", "RFC 5681 §3.2 step 3 / RFC 6582",
                      bool(ok), f"{len(enter)} recovery entries"))
    fr = ev[ev["event"] == "fast_retransmit"]
    tahoe_fr = fr[fr["flow"].map(algs) == "tahoe"]
    if len(tahoe_fr):
        out.append(_r("Tahoe: cwnd = 1 after fast retransmit", "Tahoe (no fast recovery)",
                      bool((tahoe_fr["cwnd"] == 1.0).all()), f"{len(tahoe_fr)} fast retransmits"))
    ex = ev[(ev["event"] == "exit_recovery") & ev["flow"].map(algs).isin(["newreno", "cubic"])]
    if len(ex):
        out.append(_r("NewReno/CUBIC leave fast recovery only on a full ACK", "RFC 6582 §3.2 step 5",
                      bool(ex["info"].str.contains("full ACK").all()), f"{len(ex)} exits"))

    # growth rules: consecutive cwnd records of a flow while not reducing
    viol_ss = viol_ca = n_ss = n_ca = 0
    for fid, alg in algs.items():
        c = cw[cw["flow"] == fid]
        prev_c = c["cwnd"].to_numpy()[:-1]
        nxt_c = c["cwnd"].to_numpy()[1:]
        prev_p = c["phase"].to_numpy()[:-1]
        nxt_p = c["phase"].to_numpy()[1:]
        prev_s = c["ssthresh"].to_numpy()[:-1]
        nxt_s = c["ssthresh"].to_numpy()[1:]
        same = (prev_s == nxt_s) & (nxt_c > prev_c)
        ss = same & (prev_p == "slow_start") & (nxt_p != "fast_recovery")
        n_ss += int(ss.sum())
        viol_ss += int(((nxt_c - prev_c)[ss] > 1.0 + 1e-9).sum())
        if alg in ("reno", "newreno", "tahoe"):
            ca = same & (prev_p == "congestion_avoidance") & (nxt_p == "congestion_avoidance")
            n_ca += int(ca.sum())
            viol_ca += int((~np.isclose((nxt_c - prev_c)[ca], 1.0 / prev_c[ca])).sum())
    out.append(_r("Slow start never grows cwnd by more than 1 segment per ACK", "RFC 5681 §3.1",
                  viol_ss == 0, f"{n_ss:,} slow-start increments checked, {viol_ss} violations"))
    if n_ca:
        out.append(_r("Reno-family congestion avoidance grows cwnd by exactly 1/cwnd per ACK", "RFC 5681 eq. 3",
                      viol_ca == 0, f"{n_ca:,} increments checked, {viol_ca} violations"))

    cap = cfg.bandwidth_bps * cfg.duration_s / 8
    sent = float(result.link["bytes"].sum()) if len(result.link) else 0.0
    out.append(_r("Bytes serialised never exceed link capacity x duration", "link model",
                  sent <= cap + 1e-6, f"{sent / cap * 100:.2f}% of capacity used"))
    return out


LIMITATIONS = [
    ("Segment-level model", "Sequence numbers count whole MSS-sized segments; byte-level details are not modelled."),
    ("No connection setup or teardown", "Flows start with an established connection (no SYN/FIN handshake)."),
    ("No receiver flow control dynamics", "The receive window is a fixed cap (default 10,000 segments)."),
    ("No SACK (RFC 2018/6675)", "Recovery relies on cumulative ACKs; many losses in one window often end in a timeout."),
    ("No delayed ACKs", "The receiver ACKs every segment immediately (RFC 5681 §4.2 allows delaying)."),
    ("No pacing; infinitely fast access links", "Window increases release back-to-back bursts into the bottleneck."),
    ("CUBIC without HyStart++ and with NewReno recovery", "Linux CUBIC uses HyStart++, SACK and PRR."),
    ("ACK path is uncongested and lossless", "ACKs only experience propagation delay."),
    ("Single bottleneck, drop-tail FIFO", "No RED/CoDel/ECN, no multi-hop topologies."),
    ("Loss-response FlightSize", "Segments shown received by earlier duplicate ACKs are excluded (Linux-style "
                                 "duplicate-ACK SACK emulation); equals RFC 5681 FlightSize for isolated losses."),
    ("Real-network comparison is qualitative", "Imported ss -ti traces are compared by shape and summary statistics; "
                                               "simulated cwnd is not a measurement of any OS's internal cwnd."),
]


def validation_report(results: dict[str, SimulationResult] | None = None) -> pd.DataFrame:
    rows = [dict(asdict(c), scope="rule probe") for c in rule_probes()]
    for name, res in (results or {}).items():
        rows += [dict(asdict(c), scope=f"trace: {name}") for c in audit_trace(res)]
    return pd.DataFrame(rows, columns=["scope", "check", "reference", "status", "detail"])
