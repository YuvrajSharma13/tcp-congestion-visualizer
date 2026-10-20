"""Ready-to-run experimental scenarios with expectation checks.

Each scenario builds one or more *valid* configurations and, after the runs,
compares the measured results with the qualitative behaviour the scenario is
meant to show.  A check reports what was actually measured and one of:

* ``consistent``     - the measurement agrees with the expectation
* ``not observed``   - the measurement does not show the expected behaviour
* ``info``           - an observation with no pass/fail expectation

No check assumes a particular algorithm wins; when the outcome depends on the
algorithm it is reported as an observation.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from analytics.comparison import fairness_convergence_time, recovery_episodes, startup_time
from config import defaults as D
from config.validation import ForcedDrop, LossBurst, SimulationConfig, make_config
from simulator.metrics import RunMetrics
from simulator.trace import SimulationResult

CONSISTENT, NOT_OBSERVED, INFO = "consistent", "not observed", "info"


@dataclass
class ScenarioRun:
    label: str
    config: SimulationConfig
    result: SimulationResult
    metrics: RunMetrics


@dataclass
class Check:
    expectation: str
    observed: str
    status: str


@dataclass
class Scenario:
    id: str
    title: str
    summary: str
    observe: list[str]
    build: Callable[[str], list[tuple[str, SimulationConfig]]]
    evaluate: Callable[[list[ScenarioRun]], list[Check]]
    fixed_algorithms: bool = False  # True when the scenario chooses its own algorithms
    tags: list[str] = field(default_factory=list)


def _status(ok: bool) -> str:
    return CONSISTENT if ok else NOT_OBSERVED


def _L(a: str) -> str:
    return D.ALGORITHM_LABELS.get(a, a)


def _regain(run: ScenarioRun) -> float:
    eps = [recovery_episodes(run.result, f.flow) for f in run.metrics.flows]
    vals = [v for e in eps for v in e["regain_s"].dropna().tolist()]
    return float(sorted(vals)[len(vals) // 2]) if vals else math.nan


# ---------------------------------------------------------------- 1 baseline
def _baseline_build(alg: str):
    return [("baseline", make_config(alg, duration_s=20, bandwidth_mbps=10, delay_ms=20, buffer_packets=35,
                                     loss_prob=0.0, initial_ssthresh=64))]


def _baseline_eval(runs):
    r = runs[0]
    m = r.metrics
    ev = r.result.events
    checks = [
        Check("No random losses: every drop is a buffer overflow.",
              f"random drops = {m.drops_by_type['random']}, overflow drops = {m.drops_by_type['overflow']}",
              _status(m.drops_by_type["random"] == 0)),
    ]
    ss_ca = ev[(ev["event"] == "phase_change") & ev["info"].str.startswith("slow_start->")]
    checks.append(Check("The run starts in slow start and later leaves it.",
                        f"{len(ss_ca)} transition(s) out of slow start; first at "
                        f"{ss_ca['t'].iloc[0]:.2f} s" if len(ss_ca) else "no transition out of slow start",
                        _status(len(ss_ca) > 0)))
    responses = m.fast_retransmits + m.timeouts
    checks.append(Check("Periodic overflow produces a sawtooth: repeated window reductions.",
                        f"{m.fast_retransmits} fast retransmits, {m.timeouts} timeouts", _status(responses >= 2)))
    checks.append(Check("With a buffer of about one BDP, the link stays almost fully used (> 90%).",
                        f"link utilisation = {m.link_utilisation_pct:.1f}%", _status(m.link_utilisation_pct > 90)))
    return checks


# ------------------------------------------------------------ 2 loss sweep
_LOSSES = [0.0, 0.001, 0.01, 0.02]


def _loss_build(alg: str):
    return [(f"loss {p * 100:g}%", make_config(alg, duration_s=30, bandwidth_mbps=10, delay_ms=20,
                                               buffer_packets=35, loss_prob=p)) for p in _LOSSES]


def _loss_eval(runs):
    g = [r.metrics.aggregate_goodput_mbps for r in runs]
    tol = 0.05 * max(g) if max(g) > 0 else 0
    mono = all(g[i + 1] <= g[i] + tol for i in range(len(g) - 1))
    checks = [Check("Goodput falls as the random loss rate rises.",
                    " -> ".join(f"{r.label}: {x:.2f} Mbps" for r, x in zip(runs, g)), _status(mono))]
    rnd = [r.metrics.drops_by_type["random"] for r in runs]
    checks.append(Check("More random loss means more loss events and retransmissions.",
                        ", ".join(f"{r.label}: {d} random drops" for r, d in zip(runs, rnd)),
                        _status(all(rnd[i + 1] >= rnd[i] for i in range(len(rnd) - 1)))))
    alg = runs[0].config.flows[0].algorithm
    if alg in ("reno", "newreno"):
        parts = []
        ok = True
        for r in runs[1:]:
            p = r.config.loss_prob
            rtt = (r.metrics.avg_rtt_ms or r.config.base_rtt_s * 1000) / 1000
            pred = r.config.mss_bytes * 8 / rtt * 1.22 / math.sqrt(p) / 1e6
            pred = min(pred, r.config.bandwidth_mbps)
            obs = r.metrics.aggregate_goodput_mbps
            parts.append(f"p={p:g}: Mathis {pred:.2f} vs simulated {obs:.2f} Mbps")
            if p >= 0.005:
                ok = ok and (0.4 <= obs / pred <= 2.0)
        checks.append(Check("At 1-2% loss, Reno-style goodput is of the same order as the Mathis et al. "
                            "estimate MSS/RTT x 1.22/sqrt(p) (within a factor of 2).", "; ".join(parts),
                            _status(ok)))
    return checks


# ---------------------------------------------------------- 3 shallow buffer
def _shallow_build(alg: str):
    base = dict(duration_s=30, bandwidth_mbps=10, delay_ms=20, loss_prob=0.0)
    return [("shallow buffer (4 pkts)", make_config(alg, buffer_packets=4, **base)),
            ("BDP buffer (35 pkts)", make_config(alg, buffer_packets=35, **base))]


def _shallow_eval(runs):
    s, d = runs[0].metrics, runs[1].metrics
    return [
        Check("A shallow buffer overflows more often.",
              f"overflow drops: shallow {s.drops_by_type['overflow']} vs BDP buffer {d.drops_by_type['overflow']}",
              _status(s.drops_by_type["overflow"] > d.drops_by_type["overflow"])),
        Check("A shallow buffer lowers link utilisation (the link idles after each window reduction).",
              f"utilisation: shallow {s.link_utilisation_pct:.1f}% vs BDP buffer {d.link_utilisation_pct:.1f}%",
              _status(s.link_utilisation_pct < d.link_utilisation_pct)),
        Check("A shallow buffer keeps queueing delay (RTT) low.",
              f"average RTT: shallow {s.avg_rtt_ms:.1f} ms vs BDP buffer {d.avg_rtt_ms:.1f} ms",
              _status(s.avg_rtt_ms < d.avg_rtt_ms)),
    ]


# ------------------------------------------------------------- 4 burst / RTO
def _burst_build(alg: str):
    return [("loss burst at 5 s", make_config(alg, duration_s=15, bandwidth_mbps=10, delay_ms=20,
                                              buffer_packets=35, loss_bursts=(LossBurst(5.0, 0.4),)))]


def _burst_eval(runs):
    r = runs[0]
    m = r.metrics
    to = r.result.events_of("timeout")
    checks = [Check("Consecutive losses leave too few duplicate ACKs, so a retransmission timeout fires.",
                    f"{m.drops_by_type['burst']} burst drops, {m.timeouts} timeout(s)" +
                    (f", first at {to['t'].iloc[0]:.2f} s" if len(to) else ""), _status(m.timeouts >= 1))]
    if len(to):
        cw = r.result.cwnd
        after = cw[(cw["flow"] == int(to["flow"].iloc[0])) & (cw["t"] >= to["t"].iloc[0])].iloc[0]
        checks.append(Check("After the timeout cwnd returns to one segment and slow start begins again.",
                            f"cwnd after timeout = {after['cwnd']:.1f}, phase = {after['phase']}",
                            _status(after["cwnd"] == 1.0)))
        if len(to) > 1:
            gaps = to["t"].diff().dropna()
            checks.append(Check("Repeated timeouts back off exponentially (RFC 6298).",
                                "gaps between timeouts: " + ", ".join(f"{g:.2f} s" for g in gaps[:4]), INFO))
    return checks


# ------------------------------------------------ 5 multiple losses per window
_DROPS = (ForcedDrop(0, 300), ForcedDrop(0, 303), ForcedDrop(0, 306))


def _multi_build(alg: str):
    algs = ["reno", "newreno"] + ([alg] if alg not in ("reno", "newreno") else [])
    return [(_L(a), make_config(a, duration_s=8, bandwidth_mbps=10, delay_ms=20, buffer_packets=200,
                                initial_ssthresh=32, forced_drops=_DROPS)) for a in algs]


def _multi_eval(runs):
    by = {r.config.flows[0].algorithm: r for r in runs}
    reno, nr = by["reno"].result.flow_stats[0], by["newreno"].result.flow_stats[0]
    checks = [
        Check("NewReno repairs all three holes in a single fast-recovery episode using partial ACKs.",
              f"NewReno: {nr['recovery_episodes']} recovery episode(s), {nr['partial_acks']} partial ACKs, "
              f"{nr['timeouts']} timeouts",
              _status(nr["recovery_episodes"] == 1 and nr["partial_acks"] >= 2 and nr["timeouts"] == 0)),
        Check("Classic Reno leaves fast recovery on the first partial ACK, so it needs extra reductions "
              "or a timeout.",
              f"Reno: {reno['fast_retransmits']} fast retransmits, {reno['timeouts']} timeouts, "
              f"{reno['partial_acks']} partial ACKs",
              _status(reno["fast_retransmits"] + reno["timeouts"] >= 2)),
        Check("NewReno delivers at least as much data as Reno in this scenario.",
              f"delivered segments: NewReno {nr['delivered_segments']}, Reno {reno['delivered_segments']}",
              _status(nr["delivered_segments"] >= reno["delivered_segments"])),
    ]
    for a, r in by.items():
        if a not in ("reno", "newreno"):
            st = r.result.flow_stats[0]
            checks.append(Check(f"{_L(a)} on the same three losses (observation).",
                                f"{st['fast_retransmits']} fast retransmits, {st['partial_acks']} partial ACKs, "
                                f"{st['timeouts']} timeouts, {st['delivered_segments']} segments delivered", INFO))
    return checks


# ---------------------------------------------------------------- 6 high BDP
def _hbdp_build(alg: str):
    algs = ["reno", "cubic"] + ([alg] if alg not in ("reno", "cubic") else [])
    return [(_L(a), make_config(a, duration_s=40, bandwidth_mbps=50, delay_ms=60, buffer_packets=250,
                                initial_ssthresh=300, loss_prob=1e-4, record_packet_events=False)) for a in algs]


def _hbdp_eval(runs):
    by = {r.config.flows[0].algorithm: r for r in runs}
    reno, cubic = by["reno"], by["cubic"]
    rr, rc = _regain(reno), _regain(cubic)
    checks = [
        Check(f"The path holds a large window: BDP = {reno.config.bdp_packets:.0f} packets.",
              f"base RTT {reno.config.base_rtt_s * 1000:.0f} ms at {reno.config.bandwidth_mbps:g} Mbps", INFO),
        Check("After a loss, CUBIC returns to its previous window faster than Reno's +1 segment per RTT.",
              f"median time to regain 90% of the pre-loss window: CUBIC {rc:.2f} s, Reno {rr:.2f} s"
              if not (math.isnan(rc) or math.isnan(rr)) else
              f"CUBIC {rc:.2f} s, Reno {rr:.2f} s (NaN = window never regained before the next loss or the end)",
              _status(not math.isnan(rc) and (math.isnan(rr) or rc < rr))),
        Check("CUBIC achieves at least Reno's goodput on this high-BDP path.",
              f"CUBIC {cubic.metrics.aggregate_goodput_mbps:.2f} Mbps vs Reno "
              f"{reno.metrics.aggregate_goodput_mbps:.2f} Mbps",
              _status(cubic.metrics.aggregate_goodput_mbps >= reno.metrics.aggregate_goodput_mbps)),
        Check("Timeouts (each one restarts slow start).",
              ", ".join(f"{_L(a)}: {r.metrics.timeouts}" for a, r in by.items()), INFO),
    ]
    return checks


# ---------------------------------------------------- 7 same-algorithm fairness
def _fair_build(alg: str):
    return [("two flows, second starts at 5 s",
             make_config(alg, n_flows=2, flow_start_times=[0.0, 5.0], duration_s=60, bandwidth_mbps=10,
                         delay_ms=20, buffer_packets=35, record_packet_events=False))]


def _fair_eval(runs):
    r = runs[0]
    m = r.metrics
    res = r.result
    # throughput while both are active
    d = res.deliveries
    both = d[d["t"] >= 5.0]
    shares = [both.loc[both["flow"] == f, "bytes"].sum() for f in (0, 1)]
    from analytics.fairness import jain_index
    j_both = jain_index(shares) if sum(shares) else math.nan
    conv = fairness_convergence_time(res)
    return [
        Check("Two flows with the same algorithm, RTT and loss process converge to similar shares "
              "(Jain >= 0.9 while both are active).",
              f"Jain while both active = {j_both:.3f}; per-flow goodput (whole run) = "
              + ", ".join(f"{f.goodput_mbps:.2f}" for f in m.flows) + " Mbps",
              _status(j_both >= 0.9)),
        Check("The late flow acquires a substantial share (at least 30% of what both deliver after it starts).",
              f"late flow share = {shares[1] / sum(shares) * 100:.1f}%" if sum(shares) else "no data",
              _status(sum(shares) > 0 and shares[1] / sum(shares) >= 0.3)),
        Check("Time until windowed fairness stays above 0.9.",
              f"{conv:.1f} s after the second flow starts" if not math.isnan(conv) else "not reached", INFO),
    ]


# ------------------------------------------------ 8 mixed algorithms sharing
_MIX = ["tahoe", "reno", "newreno", "cubic"]


def _mix_build(alg: str):
    return [("Tahoe + Reno + NewReno + CUBIC",
             make_config(_MIX, n_flows=4, duration_s=60, bandwidth_mbps=20, delay_ms=30, buffer_packets=100,
                         record_packet_events=False))]


def _mix_eval(runs):
    m = runs[0].metrics
    total = sum(f.goodput_mbps for f in m.flows) or 1.0
    shares = {f.algorithm: f.goodput_mbps / total for f in m.flows}
    top = max(shares, key=shares.get)
    return [
        Check("Together the flows keep the bottleneck busy (> 85% utilisation).",
              f"link utilisation = {m.link_utilisation_pct:.1f}%", _status(m.link_utilisation_pct > 85)),
        Check("Different algorithms do not split the link equally (Jain < 1).",
              f"Jain = {m.jain_index:.3f}; shares: " + ", ".join(f"{_L(a)} {s * 100:.0f}%" for a, s in shares.items()),
              INFO),
        Check("CUBIC's gentler decrease (beta = 0.7 instead of 0.5) usually earns it more than an equal "
              "(25%) share against Reno-family flows.",
              f"CUBIC share = {shares['cubic'] * 100:.1f}%; largest share: {_L(top)}",
              _status(shares["cubic"] > 0.25)),
    ]


# ------------------------------------------------------------ 9 long-delay link
def _lbhd_build(alg: str):
    return [("1 Mbps, 250 ms one-way", make_config(alg, duration_s=60, bandwidth_mbps=1, delay_ms=250,
                                                   buffer_packets=20, initial_ssthresh=64)),
            ("reference: 10 Mbps, 20 ms", make_config(alg, duration_s=60, bandwidth_mbps=10, delay_ms=20,
                                                      buffer_packets=35, initial_ssthresh=64))]


def _lbhd_eval(runs):
    sat, ref = runs
    ss_s = startup_time(sat.result, 0.8)
    ss_r = startup_time(ref.result, 0.8)
    return [
        Check("RTT is dominated by propagation delay (>= 500 ms).",
              f"average RTT = {sat.metrics.avg_rtt_ms:.0f} ms (base RTT {sat.config.base_rtt_s * 1000:.0f} ms)",
              _status(sat.metrics.avg_rtt_ms >= 500)),
        Check("Slow start takes much longer to fill the pipe because cwnd can only double once per RTT.",
              f"time to reach 80% of capacity: long-delay {ss_s:.2f} s vs reference {ss_r:.2f} s",
              _status(not math.isnan(ss_s) and (math.isnan(ss_r) or ss_s > 3 * ss_r))),
        Check("The pipe still holds only a modest window because the bandwidth is low.",
              f"BDP = {sat.config.bdp_packets:.1f} packets", INFO),
    ]


# -------------------------------------------------------------- 10 custom
def custom_scenario(cfg: SimulationConfig) -> Scenario:
    def build(alg: str):
        return [("custom", cfg)]

    def evaluate(runs):
        m = runs[0].metrics
        c = runs[0].config
        return [
            Check("Bandwidth-delay product of this configuration.",
                  f"BDP = {c.bdp_packets:.1f} packets; buffer = {c.buffer_packets} packets "
                  f"({c.buffer_packets / c.bdp_packets:.2f} x BDP)" if c.bdp_packets > 0 else "n/a", INFO),
            Check("Loss causes in this run.", ", ".join(f"{k}: {v}" for k, v in m.drops_by_type.items()), INFO),
            Check("Congestion responses.", f"{m.fast_retransmits} fast retransmits, {m.timeouts} timeouts", INFO),
        ]

    return Scenario("custom", "Custom scenario", "Your current Simulation Lab configuration.",
                    ["Use the checks as a starting point for your own explanation of the run."], build, evaluate)


SCENARIOS: list[Scenario] = [
    Scenario("baseline", "Baseline: no random loss",
             "One flow, 10 Mbps, 20 ms one-way delay, buffer about one BDP, no random loss.",
             ["Slow start (exponential growth) until ssthresh, then congestion avoidance.",
              "Losses come only from buffer overflow, producing the classic sawtooth.",
              "The link stays close to 100% busy."], _baseline_build, _baseline_eval),
    Scenario("loss_sweep", "Increasing random loss",
             "The same network at 0%, 0.1%, 1% and 2% random loss.",
             ["Goodput drops quickly as random loss grows, even though the link is not congested.",
              "For Reno/NewReno, compare with the Mathis et al. square-root formula."], _loss_build, _loss_eval),
    Scenario("shallow_buffer", "Shallow buffer and overflow",
             "A 4-packet buffer compared with a buffer of about one BDP.",
             ["Frequent overflow drops, lower utilisation, lower queueing delay with the shallow buffer."],
             _shallow_build, _shallow_eval),
    Scenario("burst_timeout", "Burst losses force a timeout",
             "All packets are lost for 400 ms starting at t = 5 s.",
             ["Too few duplicate ACKs arrive, the retransmission timer expires, cwnd returns to 1."],
             _burst_build, _burst_eval),
    Scenario("multi_loss", "Multiple losses in one window",
             "Segments 300, 303 and 306 are dropped once each; Reno and NewReno are run side by side.",
             ["NewReno stays in fast recovery and repairs each hole after a partial ACK.",
              "Reno exits on the first partial ACK and needs further reductions or a timeout."],
             _multi_build, _multi_eval, fixed_algorithms=True),
    Scenario("high_bdp", "High bandwidth-delay product",
             "50 Mbps with 60 ms one-way delay (BDP about 500 packets) and light random loss (0.01%), "
             "as on a long-haul path; Reno and CUBIC compared under identical conditions.",
             ["Reno regains its window at one segment per RTT; CUBIC's growth depends on time since the loss.",
              "Watch the concave approach to W_max in the CUBIC cwnd curve."],
             _hbdp_build, _hbdp_eval, fixed_algorithms=True),
    Scenario("fairness_same", "Two competing flows",
             "Two flows of the selected algorithm; the second starts 5 s later.",
             ["The late flow should grab bandwidth until both get similar shares."], _fair_build, _fair_eval),
    Scenario("mixed", "Different algorithms sharing a bottleneck",
             "Tahoe, Reno, NewReno and CUBIC flows share a 20 Mbps link.",
             ["Look at the per-flow goodput and Jain's index: which algorithm takes more than its share?"],
             _mix_build, _mix_eval, fixed_algorithms=True),
    Scenario("long_delay", "Low bandwidth, high delay",
             "1 Mbps with 250 ms one-way delay (satellite-like), compared with a 10 Mbps / 20 ms reference.",
             ["Slow start is slow in wall-clock time because each doubling takes one long RTT."],
             _lbhd_build, _lbhd_eval),
]

SCENARIO_BY_ID = {s.id: s for s in SCENARIOS}


def run_scenario(scenario: Scenario, algorithm: str,
                 runner: Callable[[SimulationConfig], SimulationResult],
                 progress: Callable[[int, int, str], None] | None = None) -> tuple[list[ScenarioRun], list[Check]]:
    from simulator.metrics import compute_metrics

    plans = scenario.build(algorithm)
    runs = []
    for i, (label, cfg) in enumerate(plans):
        if progress:
            progress(i, len(plans), label)
        cfg = cfg.ensure_valid()
        res = runner(cfg)
        runs.append(ScenarioRun(label, cfg, res, compute_metrics(res)))
    if progress:
        progress(len(plans), len(plans), "done")
    return runs, scenario.evaluate(runs)


def with_seed(cfg: SimulationConfig, seed: int) -> SimulationConfig:
    return replace(cfg, seed=seed)
