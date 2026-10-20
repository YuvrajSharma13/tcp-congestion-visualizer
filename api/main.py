"""FastAPI backend wrapping the simulator, analytics, ML and validation modules.

Run:  python -m uvicorn api.main:app --port 8000
Docs: http://localhost:8000/docs
"""

from __future__ import annotations

import math
import sys
import threading
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from analytics.comparison import comparison_table, interpret, run_comparison  # noqa: E402
from analytics.explain import explain_event  # noqa: E402
from analytics.scenarios import SCENARIO_BY_ID, SCENARIOS, run_scenario  # noqa: E402
from api import schemas as S  # noqa: E402
from config import defaults as D  # noqa: E402
from config.validation import ConfigValidationError, CrossTrafficConfig, LossBurst, SimulationConfig, make_config  # noqa: E402
from simulator.engine import run_simulation  # noqa: E402
from simulator.metrics import RunMetrics, compute_metrics, throughput_timeseries  # noqa: E402
from simulator.trace import SimulationResult  # noqa: E402
from storage.experiment_store import make_run_id  # noqa: E402
from visualization.charts import decimate_step, inflation_cap, phase_intervals  # noqa: E402
from visualization.playback import PlaybackUnavailable, build_journeys  # noqa: E402

app = FastAPI(title="TCP Congestion Control Visualizer API", version=D.SIMULATOR_VERSION,
              description="Discrete-event simulation of TCP Tahoe, Reno, NewReno and CUBIC (RFC 5681/6582/6298/9438).")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ------------------------------------------------------------------ caching
_CACHE: OrderedDict[str, SimulationResult] = OrderedDict()
_LOCK = threading.Lock()
CACHE_SIZE = 24


def simulate(cfg: SimulationConfig) -> SimulationResult:
    """Run or reuse a simulation. The key is the full configuration JSON (every parameter incl. seed)."""
    key = cfg.to_json()
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    res = run_simulation(cfg)
    with _LOCK:
        _CACHE[key] = res
        while len(_CACHE) > CACHE_SIZE:
            _CACHE.popitem(last=False)
    return res


def clean(v):
    """JSON-safe scalars: NaN/inf -> None, numpy -> python."""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    return v


def rows(arr) -> list[list]:
    return [[clean(x) for x in r] for r in arr]


# ------------------------------------------------------------- config build
def build_config(req: S.SimulateRequest, record_packets: bool | None = None) -> SimulationConfig:
    algs = list(req.algorithms) if req.algorithms else [req.algorithm] * req.n_flows
    starts = [i * req.flow_stagger_s for i in range(len(algs))]
    bursts = (LossBurst(req.loss_burst_start_s, req.loss_burst_ms / 1000.0),) if req.loss_burst_start_s is not None else ()
    record = req.playback if record_packets is None else record_packets
    est = req.bandwidth_mbps * 1e6 * req.duration_s / (8 * req.mss_bytes)
    try:
        cfg = make_config(
            algs, n_flows=len(algs), flow_start_times=starts, initial_cwnd=req.initial_cwnd,
            initial_ssthresh=req.initial_ssthresh, bandwidth_mbps=req.bandwidth_mbps, delay_ms=req.delay_ms,
            buffer_packets=req.buffer_packets, loss_prob=req.loss_rate / 100.0, duration_s=req.duration_s,
            seed=req.seed, mss_bytes=req.mss_bytes, min_rto_s=req.min_rto_ms / 1000.0,
            initial_rto_s=max(1.0, req.min_rto_ms / 1000.0), newreno_timer_variant=req.timer_variant,
            cross_traffic=CrossTrafficConfig(enabled=req.cross_traffic_mbps > 0, rate_mbps=req.cross_traffic_mbps),
            loss_bursts=bursts, record_packet_events=bool(record and est <= 150_000),
        )
        cfg.ensure_valid()
    except ConfigValidationError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors})
    return cfg


# ------------------------------------------------------------- serialisers
RULES = {
    "drop": "Drop-tail FIFO: arrival to a full buffer is discarded",
    "fast_retransmit": "RFC 5681 §3.2: 3 duplicate ACKs ⇒ retransmit without waiting for the RTO",
    "enter_recovery": "RFC 5681 §3.2 / RFC 6582: ssthresh = FlightSize/2, cwnd = ssthresh + 3",
    "partial_ack": "RFC 6582 §3.2: partial ACK ⇒ retransmit next hole, stay in fast recovery",
    "exit_recovery": "RFC 5681 §3.2 step 6 / RFC 6582 full ACK: deflate cwnd and leave recovery",
    "timeout": "RFC 6298 §5: RTO expiry ⇒ retransmit, back off timer; RFC 5681: cwnd = 1",
    "cwnd_reset": "RFC 5681 eq. 4: ssthresh = max(FlightSize/2, 2); cwnd = 1 (loss window)",
    "phase_change": "RFC 5681 §3.1: slow start while cwnd < ssthresh, then congestion avoidance",
}
EVENT_KINDS = ["drop", "fast_retransmit", "enter_recovery", "partial_ack", "exit_recovery", "timeout", "cwnd_reset",
               "phase_change"]


def rule_for(ev: str, alg: str, info: str) -> str:
    if ev == "drop":
        cause = info.split(":")[0]
        return {"overflow": RULES["drop"], "random": "Random link loss (configured probability, not congestion)",
                "burst": "Configured loss burst", "forced": "Scripted drop of a first transmission"}.get(cause, "")
    if alg == "cubic" and ev in ("enter_recovery", "fast_retransmit"):
        return "RFC 9438 §4.6–4.7: W_max = cwnd (fast convergence), ssthresh = 0.7 × FlightSize"
    if alg == "tahoe" and ev == "fast_retransmit":
        return "Tahoe: fast retransmit then cwnd = 1 and slow start (no fast recovery)"
    if alg == "reno" and ev == "exit_recovery" and "partial" in info:
        return "RFC 5681 Reno: any new ACK ends fast recovery, even a partial one"
    return RULES.get(ev, "")


def kpis(m: RunMetrics) -> S.Kpis:
    return S.Kpis(
        goodput_mbps=clean(m.aggregate_goodput_mbps), capacity_mbps=m.capacity_mbps,
        link_utilisation_pct=clean(m.link_utilisation_pct), goodput_utilisation_pct=clean(m.goodput_utilisation_pct),
        loss_pct=clean(m.loss_pct), jain_index=clean(m.jain_index) if m.n_flows > 1 else None,
        packets_sent=m.tcp_packets_sent, packets_dropped=m.tcp_drops, retransmissions=m.retx_packets,
        fast_retransmits=m.fast_retransmits, timeouts=m.timeouts, avg_rtt_ms=clean(m.avg_rtt_ms),
        base_rtt_ms=clean(m.base_rtt_ms), avg_cwnd=clean(m.avg_cwnd), peak_cwnd=clean(m.peak_cwnd),
        avg_queue_pkts=clean(m.avg_queue_pkts), drops_by_cause=m.drops_by_type)


def cwnd_series(res: SimulationResult, max_points: int = 2500, flows: list[int] | None = None) -> list[S.CwndSeries]:
    out = []
    for f in flows if flows is not None else range(res.config.n_flows):
        c = res.cwnd[res.cwnd["flow"] == f]
        if c.empty:
            continue
        t = c["t"].to_numpy()
        idx = np.arange(len(t))
        _, keep_idx = decimate_step(t, idx.astype(float), max_points)
        keep = keep_idx.astype(int)
        pts = np.stack([t[keep], c["cwnd"].to_numpy()[keep], c["ssthresh"].to_numpy()[keep]], axis=1)
        pts[:, 2] = np.minimum(pts[:, 2], max(float(c["cwnd"].max()) * 2, 2.0))
        pts = np.vstack([pts, [res.duration_s, pts[-1, 1], pts[-1, 2]]])
        out.append(S.CwndSeries(flow=f, algorithm=res.config.flows[f].algorithm, points=rows(pts),
                                inflation_cap=clean(inflation_cap(res, [f]))))
    return out


def events_payload(res: SimulationResult, limit: int = 400) -> tuple[list[S.EventItem], int]:
    ev = res.events[res.events["event"].isin(EVENT_KINDS)]
    # keep every non-drop congestion event first, then drops, chronological
    important = ev[ev["event"] != "phase_change"]
    total = len(important)
    sel = pd.concat([important.head(limit), ev[ev["event"] == "phase_change"].head(50)]).sort_values("t")
    items = []
    for _, r in sel.iterrows():
        alg = res.config.flows[int(r["flow"])].algorithm if r["flow"] >= 0 else "cross"
        items.append(S.EventItem(
            t=clean(r["t"]), event=r["event"], flow=int(r["flow"]), seq=int(r["seq"]), info=str(r["info"]),
            cwnd=clean(r["cwnd"]), ssthresh=clean(r["ssthresh"]), queue=int(r["queue"]),
            explanation=explain_event(res, r), rule=rule_for(r["event"], alg, str(r["info"]))))
    return items, total


def playback_payload(res: SimulationResult, t0: float, window: float, max_packets: int = 4000) -> S.Playback | None:
    try:
        j = build_journeys(res)
    except PlaybackUnavailable:
        return None
    t0 = min(t0, max(res.duration_s - window, 0.0))
    t1 = min(t0 + window, res.duration_s)
    d = j.data
    end = d[["t_rx", "t_drop", "t_tx_end"]].max(axis=1).fillna(res.duration_s)
    sel = d[(d["t_send"] <= t1) & (end >= t0)].sort_values("t_send")
    truncated = len(sel) > max_packets
    if truncated:
        sel = sel.head(max_packets)
        t1 = float(sel["t_send"].iloc[-1])
    pk = sel[["uid", "flow", "seq", "kind", "t_send", "t_enqueue", "t_tx_start", "t_tx_end", "t_rx", "t_drop",
              "drop_cause"]].astype(object).where(sel.notna(), None).to_numpy().tolist()
    a = j.acks
    a = a[(a["t_send"] <= t1) & (a["t_arrive"] >= t0)]
    cw = res.cwnd[(res.cwnd["t"] >= t0 - 1e-9) & (res.cwnd["t"] <= t1)]
    before = res.cwnd[res.cwnd["t"] < t0].groupby("flow").tail(1)
    cw = pd.concat([before.assign(t=t0), cw])
    ev = res.events[(res.events["t"] >= t0) & (res.events["t"] <= t1) &
                    res.events["event"].isin(EVENT_KINDS + ["send"])]
    ev = ev[(ev["event"] != "send") | (ev["info"] != "new")]
    return S.Playback(
        t0=t0, t1=t1, delay_s=j.delay, tx_time_s=res.config.tx_time_s, buffer_packets=res.config.buffer_packets,
        n_flows=res.config.n_flows, truncated=truncated,
        packets=[[clean(x) if not isinstance(x, str) else x for x in r] for r in pk],
        acks=rows(a[["flow", "ack", "t_send", "t_arrive"]].to_numpy()),
        cwnd=[[clean(r.t), int(r.flow), clean(r.cwnd), clean(r.ssthresh), r.phase] for r in cw.itertuples()],
        events=[[clean(r.t), r.event, int(r.flow), int(r.seq), str(r.info)] for r in ev.itertuples()])


def simulate_response(cfg: SimulationConfig, res: SimulationResult, req: S.SimulateRequest | None = None
                      ) -> S.SimulateResponse:
    m = compute_metrics(res)
    q = res.queue
    qt, qv = decimate_step(q["t"].to_numpy(), q["queue"].to_numpy().astype(float), 2500)
    rtt_rows = []
    for f in range(cfg.n_flows):
        r = res.rtt[res.rtt["flow"] == f]
        t, v = decimate_step(r["t"].to_numpy(), r["rtt_ms"].to_numpy(), 1500)
        rtt_rows += [[clean(a), f, clean(b)] for a, b in zip(t, v)]
    ts = throughput_timeseries(res)
    thr = [[clean(r.t_mid), int(r.flow), clean(r.goodput_mbps)] for r in ts.itertuples()]
    phases = [S.PhaseSpan(start=clean(r.start), end=clean(r.end), phase=r.phase)
              for r in phase_intervals(res, 0).head(600).itertuples()]
    events, total = events_payload(res)
    pb = None
    if req is not None and req.playback:
        pb = playback_payload(res, req.playback_start_s, req.playback_window_s)
    return S.SimulateResponse(
        run_id=make_run_id(cfg), config=cfg.to_dict(), bdp_packets=clean(cfg.bdp_packets), kpis=kpis(m),
        flows=[S.FlowKpi(flow=f.flow, algorithm=f.algorithm, goodput_mbps=clean(f.goodput_mbps),
                         loss_pct=clean(f.loss_pct), fast_retransmits=f.fast_retransmits, timeouts=f.timeouts,
                         avg_rtt_ms=clean(f.avg_rtt_ms), avg_cwnd=clean(f.avg_cwnd)) for f in m.flows],
        cwnd=cwnd_series(res), phases=phases, queue=rows(np.stack([qt, qv], axis=1)), rtt=rtt_rows,
        throughput=thr, events=events, events_total=total, playback=pb,
        run_info={k: clean(v) if not isinstance(v, str) else v for k, v in res.run_info.items()})


# ------------------------------------------------------------------ routes
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "simulator_version": D.SIMULATOR_VERSION, "algorithms": list(D.ALGORITHMS)}


@app.post("/api/simulate", response_model=S.SimulateResponse)
def api_simulate(req: S.SimulateRequest) -> S.SimulateResponse:
    cfg = build_config(req)
    return simulate_response(cfg, simulate(cfg), req)


@app.post("/api/compare", response_model=S.CompareResponse)
def api_compare(req: S.CompareRequest) -> S.CompareResponse:
    base = build_config(req, record_packets=False)
    runs = run_comparison(base, list(dict.fromkeys(req.compare)), runner=simulate)
    table = comparison_table(runs)
    out_rows = [S.CompareRow(**{k: clean(v) if not isinstance(v, str) else v for k, v in r.items()})
                for r in table.to_dict("records")]
    if base.n_flows == 1:  # fairness is undefined for a single flow
        for r in out_rows:
            r.jain_index = None
    series = []
    for r in runs:
        series += cwnd_series(r.result, 1500, flows=[0])
    return S.CompareResponse(config=base.to_dict(), rows=out_rows, cwnd=series, notes=interpret(table, base))


@app.get("/api/scenarios", response_model=list[S.ScenarioInfo])
def api_scenarios() -> list[S.ScenarioInfo]:
    return [S.ScenarioInfo(id=s.id, title=s.title, summary=s.summary, observe=s.observe,
                           fixed_algorithms=s.fixed_algorithms, runs=[lab for lab, _ in s.build("reno")])
            for s in SCENARIOS]


@app.post("/api/scenarios/{scenario_id}/run", response_model=S.ScenarioRunResponse)
def api_run_scenario(scenario_id: str, req: S.ScenarioRunRequest | None = None) -> S.ScenarioRunResponse:
    sc = SCENARIO_BY_ID.get(scenario_id)
    if sc is None:
        raise HTTPException(404, f"Unknown scenario {scenario_id!r}; see GET /api/scenarios")
    alg = (req or S.ScenarioRunRequest()).algorithm

    def runner(cfg):
        return simulate(replace(cfg, record_packet_events=False))

    runs, checks = run_scenario(sc, alg, runner)
    return S.ScenarioRunResponse(
        id=sc.id, title=sc.title,
        checks=[S.CheckItem(expectation=c.expectation, observed=c.observed, status=c.status) for c in checks],
        runs=[S.ScenarioRunItem(label=r.label, config=r.config.to_dict(), kpis=kpis(r.metrics),
                                cwnd=cwnd_series(r.result, 1200)) for r in runs])


@app.post("/api/predict", response_model=S.PredictResponse)
def api_predict(req: S.SimulateRequest) -> S.PredictResponse:
    from ml.predict import explain_prediction, explanation_text, load_model, predict_run, risk_level

    status = load_model()
    if not status.ok:
        return S.PredictResponse(available=False, message=status.message)
    b = status.bundle
    cfg = build_config(req, record_packets=False)
    res = simulate(cfg)
    pred = predict_run(b, res)
    if pred.empty:
        return S.PredictResponse(available=False, message="Run too short for a full feature window.")
    step = max(len(pred) // 1500, 1)
    pts = [[clean(r.t), clean(r.prob), r.risk, clean(r.actual)] for r in pred.iloc[::step].itertuples()]
    peak_row = pred.loc[pred["prob"].idxmax()]
    contrib = explain_prediction(b, peak_row)
    known = pred[pred["actual"].notna()]
    from ml.evaluate import classification_metrics
    rm = classification_metrics(known["actual"].to_numpy(), known["prob"].to_numpy(), b["threshold"]) \
        if len(known) else None
    ev = b["evaluation"]
    return S.PredictResponse(
        available=True, message=status.message, horizon_s=b["horizon_s"], window_s=b["window_s"], model=b["chosen"],
        threshold=b["threshold"], points=pts,
        peak={"t": clean(peak_row["t"]), "prob": clean(peak_row["prob"]), "risk": risk_level(peak_row["prob"]),
              "mean_prob": clean(pred["prob"].mean()),
              "high_fraction": clean((pred["risk"] == "high").mean())},
        contributions=[S.Contribution(feature=r.feature, label=r.label, value=clean(r.value),
                                      contribution=clean(r.contribution)) for r in contrib.itertuples()],
        explanation=explanation_text(contrib),
        evaluation={k: {m: clean(v[m]) for m in ("precision", "recall", "f1", "roc_auc", "brier")}
                    for k, v in ev.items()},
        importance={k: clean(v) for k, v in b["permutation_importance"].items()},
        run_metrics={k: clean(v) for k, v in rm.items()} if rm else None)


@app.get("/api/validation", response_model=S.ValidationResponse)
def api_validation() -> S.ValidationResponse:
    from validation.rfc_checks import LIMITATIONS, audit_trace, rule_probes

    cfg = make_config(["tahoe", "reno", "newreno", "cubic"], n_flows=4, duration_s=15, buffer_packets=20,
                      loss_prob=0.003, loss_bursts=(LossBurst(8.0, 0.5),), record_packet_events=False)
    res = simulate(cfg)
    items = [S.ValidationItem(scope="rule probe", **c.__dict__) for c in rule_probes()]
    items += [S.ValidationItem(scope="trace audit", **c.__dict__) for c in audit_trace(res)]
    return S.ValidationResponse(
        passed=sum(i.status == "pass" for i in items), failed=sum(i.status == "fail" for i in items),
        not_applicable=sum(i.status not in ("pass", "fail") for i in items), items=items,
        limitations=[list(x) for x in LIMITATIONS],
        audited_run="4 flows (Tahoe, Reno, NewReno, CUBIC), 10 Mbps, 20 ms, 20-pkt buffer, 0.3% loss, burst at 8 s")


# ------------------------------------------- serve the built frontend if present
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
