# Architecture

```
config/        validated, frozen SimulationConfig (+ JSON round trip), defaults & limits
simulator/     events.py (heap + tie-breaking) · network.py (link, drop-tail, receiver) · rto.py (RFC 6298)
               flow.py (TCP sender) · engine.py (discrete-event loop) · trace.py (recorded tables)
               metrics.py (goodput, utilisation, loss, RTT, cwnd, Jain)
algorithms/    base.py (CongestionControl interface) · tahoe · reno · newreno · cubic
analytics/     comparison · fairness · sensitivity · scenarios (10 presets + checks) · explain (rule-based)
visualization/ theme · charts (Plotly) · topology · playback (state reconstruction from the event log)
reporting/     export_csv · export_json · report (self-contained HTML) · static_plots (Matplotlib PNG/SVG)
storage/       experiment_store.py (SQLite: runs + presets, data/experiments.db)
validation/    rfc_checks.py (rule probes + trace audits) · real_trace.py (ss -tin import)
ml/            dataset · train · evaluate · predict (read-only, never touches the simulator)
learning/      lessons · quiz
ui/            state (cache, history) · components · views/ (one module per page)
app.py         Streamlit navigation
tools/         capture_ss_trace.sh (optional Linux/WSL capture)
tests/         pytest suite
```

Data flow: `SimulationConfig → Simulator.run() → SimulationResult (events, cwnd, queue, rtt, deliveries, link,
samples)` → metrics / charts / playback / exports / ML features. The simulator imports nothing from Streamlit; the
same engine serves the dashboard, tests, exports and ML data generation.

Separation of concerns: the **sender** (simulator/flow.py) owns sequence numbers, duplicate-ACK counting, the RTO
timer and transmissions; an **algorithm** owns cwnd, ssthresh and recovery state and replies with a `CCResponse`
(retransmit head, go-back-N, restart timer, events to log).

Caching: `ui/state.simulate()` caches results keyed by the full configuration JSON (all parameters including seed);
results are treated as immutable. Session history keeps full traces for the last 12 runs; SQLite keeps configs and
metrics permanently.
