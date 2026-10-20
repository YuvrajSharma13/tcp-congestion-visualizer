"""Metric definitions, units and edge cases."""

import math

import numpy as np
import pytest

from analytics.fairness import fairness_label, jain_index
from config.validation import make_config
from simulator import trace as T
from simulator.engine import run_simulation
from simulator.metrics import (compute_metrics, flow_metrics_frame, link_utilisation_timeseries,
                               throughput_timeseries, time_weighted_mean)


# ------------------------------------------------------------------ Jain
@pytest.mark.parametrize("xs, expected", [
    ([5, 5, 5], 1.0),
    ([1, 0, 0], 1 / 3),
    ([3, 1], 16 / 20),
    ([2], 1.0),
    ([10, 0], 0.5),
])
def test_jain_index_known_values(xs, expected):
    assert jain_index(xs) == pytest.approx(expected)


def test_jain_index_undefined_and_invalid():
    assert math.isnan(jain_index([]))
    assert math.isnan(jain_index([0, 0, 0]))
    assert fairness_label(float("nan")) == "undefined"
    with pytest.raises(ValueError):
        jain_index([1, -1])
    with pytest.raises(ValueError):
        jain_index([1, float("inf")])


# ------------------------------------------------------------ step means
def test_time_weighted_mean():
    t = np.array([0.0, 1.0, 3.0])
    v = np.array([2.0, 4.0, 0.0])
    assert time_weighted_mean(t, v, 0.0, 4.0) == pytest.approx((2 * 1 + 4 * 2 + 0 * 1) / 4)
    assert time_weighted_mean(t, v, 2.0, 3.0) == pytest.approx(4.0)
    assert math.isnan(time_weighted_mean(t, v, 1.0, 1.0))
    assert math.isnan(time_weighted_mean(np.array([]), np.array([]), 0.0, 1.0))


# ------------------------------------------------------- synthetic result
def _synthetic(deliveries, link, sent, drops, duration=2.0, bw=10.0):
    cfg = make_config("reno", duration_s=duration, bandwidth_mbps=bw, mss_bytes=1000)
    rec = T.TraceRecorder()
    rec.deliveries = deliveries
    rec.link = link
    rec.cwnd = [(0.0, 0, 1.0, 64.0, "slow_start"), (1.0, 0, 3.0, 64.0, "slow_start")]
    rec.rtt = [(0.5, 0, 0.040), (1.5, 0, 0.060)]
    stats = [{"flow": 0, "algorithm": "reno", "start_time_s": 0.0, "sent_packets": sent, "retx_packets": 1,
              "drops": drops, "timeouts": 0, "fast_retransmits": 1, "partial_acks": 0,
              "drops_overflow": drops, "drops_random": 0, "drops_burst": 0, "drops_forced": 0}]
    return T.build_result(cfg, rec, stats, {})


def test_goodput_units_and_loss_percentage():
    # 1000 segments of 1000 B in 2 s -> 8,000,000 bits / 2 s = 4 Mbps
    res = _synthetic([(0.5, 0, 500), (1.5, 0, 500)], [(0.1, 0, 1000, False)] * 10, sent=1010, drops=10)
    m = compute_metrics(res)
    assert m.aggregate_goodput_mbps == pytest.approx(4.0)
    assert m.flows[0].goodput_mbps == pytest.approx(4.0)
    assert m.goodput_utilisation_pct == pytest.approx(40.0)
    assert m.loss_pct == pytest.approx(10 / 1010 * 100)
    assert m.avg_rtt_ms == pytest.approx(50.0)
    assert m.flows[0].avg_cwnd == pytest.approx((1 * 1 + 3 * 1) / 2)
    assert m.flows[0].peak_cwnd == 3.0
    assert m.link_utilisation_pct == pytest.approx(10 * 1000 * 8 / (10e6 * 2) * 100)


def test_throughput_timeseries_conserves_bytes_and_handles_partial_last_bin():
    res = _synthetic([(0.05, 0, 100), (1.95, 0, 100)], [], sent=200, drops=0, duration=2.0)
    ts = throughput_timeseries(res, bin_s=0.3)  # 2.0 / 0.3 -> last bin is 0.2 s wide
    widths = ts["t_end"] - ts["t_start"]
    assert widths.iloc[-1] == pytest.approx(0.2)
    total_bits = (ts["goodput_mbps"] * 1e6 * widths).sum()
    assert total_bits == pytest.approx(200 * 1000 * 8)
    assert ts["goodput_mbps"].iloc[-1] == pytest.approx(100 * 1000 * 8 / 0.2 / 1e6)


def test_empty_trace_does_not_crash():
    res = _synthetic([], [], sent=0, drops=0)
    res.rtt = res.rtt.iloc[0:0]
    m = compute_metrics(res)
    assert m.aggregate_goodput_mbps == 0.0
    assert m.loss_pct == 0.0
    assert math.isnan(m.avg_rtt_ms)
    assert math.isnan(m.jain_index)  # one flow with zero goodput: undefined
    d = m.to_dict()
    assert d["avg_rtt_ms"] is None   # NaN becomes null in exports
    assert len(throughput_timeseries(res)) > 0
    assert link_utilisation_timeseries(res)["util_pct"].sum() == 0


def test_flow_that_starts_late_reports_zero_safely():
    res = run_simulation(make_config(["reno", "reno"], n_flows=2, flow_start_times=[0.0, 2.95], duration_s=3.0))
    m = compute_metrics(res)
    late = m.flows[1]
    assert late.active_duration_s == pytest.approx(0.05)
    assert late.goodput_mbps >= 0.0
    assert flow_metrics_frame(m).shape[0] == 2


# --------------------------------------------------------- real runs
def test_link_utilisation_bounded_and_high_on_saturated_baseline():
    m = compute_metrics(run_simulation(make_config("reno", duration_s=20, buffer_packets=40)))
    assert 0 <= m.link_utilisation_pct <= 100
    assert m.link_utilisation_pct > 90
    assert m.goodput_utilisation_pct <= m.link_utilisation_pct + 1e-9


def test_retransmissions_do_not_inflate_goodput():
    res = run_simulation(make_config("tahoe", duration_s=10, loss_prob=0.03, buffer_packets=10))
    m = compute_metrics(res)
    st = res.flow_stats[0]
    assert st["retx_packets"] > 0
    unique_bits = st["delivered_segments"] * res.config.mss_bytes * 8
    assert m.flows[0].goodput_mbps == pytest.approx(unique_bits / 10 / 1e6)
    link_tcp_bits = res.link.loc[res.link["flow"] == 0, "bytes"].sum() * 8
    assert unique_bits < link_tcp_bits


def test_jain_index_for_identical_flows_is_high():
    res = run_simulation(make_config("reno", n_flows=2, duration_s=30, buffer_packets=40))
    m = compute_metrics(res)
    assert 0.5 <= m.jain_index <= 1.0
    assert m.jain_index == pytest.approx(jain_index([f.goodput_mbps for f in m.flows]))
