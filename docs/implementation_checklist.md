# Implementation checklist

Status: **tested** = implemented with automated tests; **implemented** = working and verified manually/headlessly but not unit-tested; **partial**; **not implemented**.

| Feature | Status | Relevant files | Evidence | Known limitations |
|---|---|---|---|---|
| Discrete-event engine, deterministic tie-breaking, limits | tested | simulator/events.py, engine.py | test_engine.py (ordering, ties, duration, event limit) | single-threaded Python (~150k events/s) |
| Bottleneck link, drop-tail FIFO, serialization/propagation/queueing delay | tested | simulator/network.py | test_network.py, test_engine.py timing & buffer tests | one bottleneck, no AQM |
| Receiver with cumulative ACKs, reassembly, no double delivery | tested | simulator/network.py | test_network.py, test_delivered_data_is_never_counted_twice | no delayed ACK/SACK |
| Random loss, loss bursts, scripted drops, all logged | tested | simulator/engine.py | test_every_drop_is_logged, test_random_loss_rate, burst/forced tests | data packets only; ACKs never lost |
| RFC 6298 RTO, Karn, back-off, no stale timeouts | tested | simulator/rto.py, flow.py | test_network.py RTO tests, test_timeouts_only_for_outstanding_data | min RTO default 1 s |
| Tahoe | tested | algorithms/tahoe.py | test_tahoe.py (8) | go-back-N after fast retransmit (ns-2 style) |
| Reno | tested | algorithms/reno.py | test_reno.py (8) | — |
| NewReno (partial ACKs, recover, Impatient/Slow-but-Steady) | tested | algorithms/newreno.py | test_newreno.py (8) | — |
| CUBIC (W(t), K, W_max, fast convergence, Reno-friendly, timeout) | tested | algorithms/cubic.py | test_cubic.py (10) incl. end-to-end plateau at K | NewReno recovery, no HyStart++ |
| Multiple competing flows, cross traffic | tested | simulator/engine.py | test_cross_traffic_shares_the_link, multi-flow tests | same RTT for all flows |
| Reproducibility (seed, JSON round trip) | tested | config/validation.py | test_reproducibility.py | — |
| Input validation with useful messages | tested | config/validation.py, ui/components.py | parametrised invalid-config tests, test_lab_shows_validation_errors | — |
| Metrics (goodput, utilisation, loss, RTT, cwnd, queue, edge cases) | tested | simulator/metrics.py | test_metrics.py | per-bin utilisation clipped at 100% |
| Jain's fairness index | tested | analytics/fairness.py | known-value and NaN tests | — |
| Controlled algorithm comparison + interpretation | tested | analytics/comparison.py, ui/views/comparison.py | test_comparison_uses_identical_conditions, UI test | loss patterns statistically, not packet-identical |
| Recovery / convergence metrics | tested | analytics/comparison.py | test_recovery_episode_regain_time | heuristic definitions (90% regain) |
| 10 scenarios with expected-vs-observed checks | tested | analytics/scenarios.py, ui/views/scenarios.py | test_every_scenario_builds_valid_configs, multi-loss checks, UI test | checks are qualitative thresholds |
| Sensitivity analysis (multi-seed, 95% CI) | tested | analytics/sensitivity.py, ui/views/sensitivity.py | test_sensitivity_sweep_and_summary | max 120 runs per sweep |
| Rule-based event explanations | tested | analytics/explain.py | test_explanations_are_grounded_in_the_event_log | — |
| CSV / JSON exports, config import | tested | reporting/export_csv.py, export_json.py | test_exports.py | — |
| HTML report (self-contained) | tested | reporting/report.py | test_experiments_page_exports_after_a_run | ~5 MB (embeds plotly.js) |
| PNG/SVG figures | implemented | reporting/static_plots.py | rendered and inspected | Matplotlib (Plotly export needs Chrome) |
| SQLite history + named presets | tested | storage/experiment_store.py | test_experiment_store_runs_and_presets | configs + metrics only, not traces |
| Dashboard: 10 pages, dark theme | tested (smoke + interactions) | app.py, ui/ | test_ui.py (20 AppTest tests), headless-browser screenshots | visual layout checked on 1440 px only |
| Packet playback from event trace | tested | visualization/playback.py, topology.py, ui/views/playback.py | test_packet_playback_demo_steps_forward_and_back | needs per-packet logging; 2000 events per window |
| Phase identification (SS/CA/FR), event markers | implemented | visualization/charts.py | trace audit + screenshots | — |
| Learning Centre: lessons, quiz, prediction challenge | tested | learning/, ui/views/learning.py | test_learning_quiz_scores_answers | — |
| ML congestion prediction (leakage-safe, grouped split, baselines, calibration, importance) | tested | ml/ | test_ml.py (10); held-out ROC-AUC 0.913 | simulated telemetry only; read-only |
| RFC validation module & report | tested | validation/rfc_checks.py, docs/validation.md | 35/35 checks pass; tamper test detects failures | checks modelled rules only |
| Real Linux trace import & comparison | tested | validation/real_trace.py, tools/capture_ss_trace.sh, data/real_traces | parser test on bundled real captures | shape comparison only |
| BBR / Vegas / AQM / SACK | not implemented | — | — | future work (report §11) |
