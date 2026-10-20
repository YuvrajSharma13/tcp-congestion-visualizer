"""Exports, saved configurations, experiment store and validation helpers."""

import io
import json
from pathlib import Path

import pandas as pd
import pytest

from analytics.comparison import comparison_table, interpret, recovery_episodes, run_comparison
from analytics.explain import explain_event
from analytics.scenarios import SCENARIO_BY_ID, SCENARIOS, run_scenario
from analytics.sensitivity import parse_values, run_sensitivity, summarize
from config.validation import ConfigValidationError, ForcedDrop, LossBurst, make_config
from reporting.export_csv import events_csv, metrics_csv, timeseries_csv
from reporting.export_json import config_json, load_config_json
from simulator.engine import run_simulation
from simulator.metrics import compute_metrics
from storage.experiment_store import ExperimentStore, make_run_id
from validation.real_trace import compare, main_connection, parse_ss_trace
from validation.rfc_checks import FAIL, audit_trace, rule_probes, validation_report

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def run():
    cfg = make_config(["reno", "cubic"], n_flows=2, duration_s=4, loss_prob=0.01, buffer_packets=15)
    res = run_simulation(cfg)
    return cfg, res, compute_metrics(res)


def test_events_csv_has_documented_columns(run):
    _, res, _ = run
    df = pd.read_csv(io.BytesIO(events_csv(res)))
    assert list(df.columns) == ["t", "event", "flow", "seq", "uid", "info", "cwnd", "ssthresh", "queue"]
    assert len(df) == len(res.events)
    assert set(df["event"]) >= {"send", "drop", "rx", "ack_rx"}


def test_metrics_csv_rows_and_values(run):
    _, res, m = run
    df = pd.read_csv(io.BytesIO(metrics_csv(m, run_id="R1")))
    assert list(df["flow"].astype(str)) == ["0", "1", "all"]
    assert (df["run_id"] == "R1").all()
    for col in ("goodput_mbps", "loss_pct", "avg_rtt_ms", "timeouts", "fast_retransmits", "jain_index"):
        assert col in df.columns
    assert df.loc[2, "goodput_mbps"] == pytest.approx(m.aggregate_goodput_mbps)
    assert df.loc[0, "goodput_mbps"] == pytest.approx(m.flows[0].goodput_mbps)


def test_timeseries_csv(run):
    _, res, _ = run
    df = pd.read_csv(io.BytesIO(timeseries_csv(res)))
    assert {"t", "flow", "cwnd", "ssthresh", "queue", "srtt_ms"} <= set(df.columns)
    assert len(df) == len(res.samples) > 0


def test_config_json_round_trip_and_metadata(run):
    cfg, _, m = run
    text = config_json(cfg, run_id="R42", name="demo", metrics=m.to_dict())
    doc = json.loads(text)
    assert doc["run_id"] == "R42" and doc["config"]["seed"] == cfg.seed
    assert doc["simulator_version"] and doc["config_version"] == 1
    cfg2, meta = load_config_json(text)
    assert cfg2 == cfg and meta["name"] == "demo"


def test_config_json_rejects_invalid_files():
    with pytest.raises(ConfigValidationError, match="not valid JSON"):
        load_config_json("{nope")
    with pytest.raises(ConfigValidationError, match="Unknown configuration field"):
        load_config_json(json.dumps({"config": {"bandwidth": 5}}))
    bad = json.loads(config_json(make_config("reno")))
    bad["config"]["buffer_packets"] = 0
    with pytest.raises(ConfigValidationError, match="Buffer capacity"):
        load_config_json(json.dumps(bad))


def test_config_with_bursts_and_forced_drops_round_trip():
    cfg = make_config("newreno", loss_bursts=(LossBurst(1.0, 0.2),), forced_drops=(ForcedDrop(0, 9),))
    cfg2, _ = load_config_json(config_json(cfg))
    assert cfg2 == cfg


def test_experiment_store_runs_and_presets(tmp_path, run):
    cfg, _, m = run
    store = ExperimentStore(tmp_path / "x.db")
    rid = make_run_id(cfg)
    store.save_run(rid, cfg, m.to_dict(), label="first")
    table = store.runs_table()
    assert table.loc[0, "run_id"] == rid and table.loc[0, "label"] == "first"
    assert table.loc[0, "goodput_mbps"] == pytest.approx(m.aggregate_goodput_mbps)
    cfg_back, metrics_back = store.get_run(rid)
    assert cfg_back == cfg and metrics_back["timeouts"] == m.timeouts
    # presets reload to the identical configuration and reproduce the run
    store.save_preset("my preset", cfg, "desc")
    assert list(store.list_presets()["name"]) == ["my preset"]
    loaded = store.load_preset("my preset")
    assert loaded == cfg
    a, b = run_simulation(cfg), run_simulation(loaded)
    pd.testing.assert_frame_equal(a.cwnd, b.cwnd)
    with pytest.raises(ValueError):
        store.save_preset("  ", cfg)
    with pytest.raises(KeyError):
        store.load_preset("missing")
    assert store.delete_preset("my preset") and store.delete_run(rid)
    assert store.runs_table().empty
    # a fresh store on the same file still works (persistence)
    store.save_run(rid, cfg, m.to_dict())
    assert len(ExperimentStore(tmp_path / "x.db").list_runs()) == 1


def test_comparison_uses_identical_conditions():
    base = make_config("reno", n_flows=2, flow_start_times=[0, 1], duration_s=4, loss_prob=0.005, seed=11)
    runs = run_comparison(base, ["tahoe", "reno", "newreno", "cubic"])
    for r in runs:
        c = r.config
        assert all(f.algorithm == r.algorithm for f in c.flows)
        assert (c.seed, c.bandwidth_mbps, c.loss_prob, c.buffer_packets) == (11, base.bandwidth_mbps, 0.005,
                                                                            base.buffer_packets)
        assert [f.start_time_s for f in c.flows] == [0, 1]
    table = comparison_table(runs)
    assert list(table["algorithm"]) == ["tahoe", "reno", "newreno", "cubic"]
    notes = interpret(table, base)
    assert notes and any("Caveat" in n for n in notes)


def test_recovery_episode_regain_time():
    res = run_simulation(make_config("reno", duration_s=6, forced_drops=(ForcedDrop(0, 200),), buffer_packets=200,
                                     initial_ssthresh=32))
    eps = recovery_episodes(res, 0)
    assert len(eps) == 1
    row = eps.iloc[0]
    assert row["min_cwnd_after"] < row["pre_cwnd"]
    # Reno halves, then grows ~1 segment per RTT: regaining 90% takes roughly (0.4 * W) RTTs
    assert row["regain_s"] > 0


def test_sensitivity_sweep_and_summary():
    base = make_config("reno", duration_s=3)
    df = run_sensitivity(base, "buffer_packets", [5, 40], ["reno"], [1, 2])
    assert len(df) == 4
    s = summarize(df, "goodput_mbps")
    assert list(s["count"]) == [2, 2]
    assert (s["ci95"] >= 0).all()
    assert parse_values("5:20:5", "buffer_packets") == [5.0, 10.0, 15.0, 20.0]
    assert parse_values("0.01, 0.001", "loss_prob") == [0.001, 0.01]
    with pytest.raises(ValueError):
        run_sensitivity(base, "mss_bytes", [1000], ["reno"], [1])
    with pytest.raises(ValueError):
        run_sensitivity(base, "buffer_packets", list(range(1, 50)), ["reno", "cubic"], [1, 2])


def test_every_scenario_builds_valid_configs():
    for sc in SCENARIOS:
        for alg in ("tahoe", "cubic"):
            plans = sc.build(alg)
            assert plans
            for _, cfg in plans:
                assert cfg.validate() == []


def test_multi_loss_scenario_checks():
    runs, checks = run_scenario(SCENARIO_BY_ID["multi_loss"], "reno", run_simulation)
    assert {c.status for c in checks} <= {"consistent", "not observed", "info"}
    assert checks[0].status == "consistent"   # NewReno single recovery with partial ACKs


def test_explanations_are_grounded_in_the_event_log():
    res = run_simulation(make_config("newreno", duration_s=8, buffer_packets=200, initial_ssthresh=32,
                                     forced_drops=(ForcedDrop(0, 300), ForcedDrop(0, 303)),
                                     loss_bursts=(LossBurst(5.0, 0.4),)))
    ev = res.events
    fr = ev[ev["event"] == "fast_retransmit"].iloc[0]
    text = explain_event(res, fr)
    assert "three duplicate ACKs" in text and f"segment {int(fr['seq'])}" in text
    pa = ev[ev["event"] == "partial_ack"].iloc[0]
    assert "Partial ACK" in explain_event(res, pa)
    to = ev[ev["event"] == "timeout"].iloc[0]
    assert "Retransmission timeout" in explain_event(res, to)
    drop = ev[(ev["event"] == "drop") & (ev["info"] == "forced")].iloc[0]
    assert "Scripted loss" in explain_event(res, drop)
    for _, row in ev.sample(200, random_state=1).iterrows():
        assert isinstance(explain_event(res, row), str)


def test_validation_rule_probes_and_audit_pass():
    probes = rule_probes()
    assert probes and all(p.status == "pass" for p in probes), [p for p in probes if p.status != "pass"]
    res = run_simulation(make_config(["tahoe", "newreno"], n_flows=2, duration_s=6, loss_prob=0.01,
                                     buffer_packets=10, loss_bursts=(LossBurst(3, 0.5),)))
    audit = audit_trace(res)
    assert all(a.status != FAIL for a in audit), [a for a in audit if a.status == FAIL]
    rep = validation_report({"x": res})
    assert set(rep.columns) == {"scope", "check", "reference", "status", "detail"}


def test_audit_detects_a_broken_trace():
    res = run_simulation(make_config("reno", duration_s=3, buffer_packets=10))
    res.queue.loc[len(res.queue)] = (1.0, 999)   # tamper: impossible queue length
    statuses = {a.check: a.status for a in audit_trace(res)}
    assert statuses["Queue occupancy stays within [0, buffer]"] == FAIL


def test_real_trace_parser_on_bundled_linux_capture():
    path = ROOT / "data" / "real_traces" / "linux_reno_lo_tbf10mbit.txt"
    df = parse_ss_trace(path.read_text())
    main = main_connection(df)
    assert set(main["algorithm"]) == {"reno"}
    assert main["mss"].iloc[0] == 1448
    assert main["ssthresh"].dropna().max() < 1000  # rcv_ssthresh must not be mistaken for ssthresh
    assert (main["t"].diff().dropna() > 0).all()
    res = run_simulation(make_config("reno", duration_s=5, delay_ms=0.0, buffer_packets=40, mss_bytes=1448))
    cmp = compare(main, res)
    assert {"mean_cwnd", "reductions_per_10s"} <= set(cmp["statistic"])


def test_real_trace_parser_rejects_garbage():
    from validation.real_trace import TraceFormatError
    with pytest.raises(TraceFormatError):
        parse_ss_trace("hello\nworld\n")
