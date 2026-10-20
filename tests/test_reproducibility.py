"""A fixed configuration and seed must reproduce a run exactly."""

import pandas as pd

from config.validation import SimulationConfig, make_config
from simulator.engine import run_simulation
from simulator.metrics import compute_metrics


def _cfg(seed=7, alg="cubic"):
    return make_config([alg, "reno"], n_flows=2, flow_start_times=[0.0, 0.5], duration_s=5,
                       loss_prob=0.01, buffer_packets=12, seed=seed)


def test_same_seed_same_trace_and_metrics():
    a, b = run_simulation(_cfg()), run_simulation(_cfg())
    pd.testing.assert_frame_equal(a.events, b.events)
    pd.testing.assert_frame_equal(a.cwnd, b.cwnd)
    pd.testing.assert_frame_equal(a.samples, b.samples)
    assert compute_metrics(a).to_dict() == compute_metrics(b).to_dict()


def test_different_seed_changes_random_losses():
    a, b = run_simulation(_cfg(seed=1)), run_simulation(_cfg(seed=2))
    da = a.events_of("drop")[["t", "seq"]].to_numpy().tolist()
    db = b.events_of("drop")[["t", "seq"]].to_numpy().tolist()
    assert da != db


def test_config_json_round_trip_reproduces_run():
    cfg = _cfg()
    cfg2 = SimulationConfig.from_json(cfg.to_json())
    assert cfg2 == cfg
    a, b = run_simulation(cfg), run_simulation(cfg2)
    pd.testing.assert_frame_equal(a.events, b.events)


def test_deterministic_without_randomness_regardless_of_seed():
    a = run_simulation(make_config("reno", duration_s=4, seed=1))
    b = run_simulation(make_config("reno", duration_s=4, seed=999))
    pd.testing.assert_frame_equal(a.cwnd, b.cwnd)
