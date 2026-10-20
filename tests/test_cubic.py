"""TCP CUBIC window function and state transitions (RFC 9438)."""

import math

import pytest

from algorithms.cubic import CubicCC
from config.validation import ForcedDrop, make_config
from simulator.engine import run_simulation
from tests.helpers import info


def test_default_parameters_match_rfc9438():
    cc = CubicCC()
    assert cc.c == 0.4 and cc.beta == 0.7
    assert cc.alpha_aimd == pytest.approx(3 * 0.3 / 1.7)


def test_k_formula_matches_report():
    # K = cbrt(W_max * (1 - beta) / C) when cwnd_epoch = beta * W_max
    k = CubicCC.compute_k(100.0, 70.0, 0.4)
    assert k == pytest.approx((100 * 0.3 / 0.4) ** (1 / 3))
    assert k == pytest.approx(4.2172, abs=1e-4)


def test_window_function_passes_through_epoch_and_wmax():
    cc = CubicCC(1, 64)
    cc.w_max, cc.k = 100.0, CubicCC.compute_k(100.0, 70.0, 0.4)
    assert cc.w_cubic(0.0) == pytest.approx(70.0)   # starts at cwnd_epoch
    assert cc.w_cubic(cc.k) == pytest.approx(100.0)  # plateau at W_max after K seconds
    assert cc.w_cubic(cc.k + 1) == pytest.approx(100.4)   # convex: C * 1^3 above W_max
    assert cc.w_cubic(cc.k - 1) == pytest.approx(99.6)    # concave side


def test_multiplicative_decrease_uses_beta():
    cc = CubicCC(100, 50)
    r = cc.on_dupack(info(ack=10, flight=100, snd_max=110), 3)
    assert r.retransmit_head and cc.in_recovery
    assert cc.w_max == pytest.approx(100.0)
    assert cc.ssthresh == pytest.approx(70.0)
    assert cc.cwnd == pytest.approx(73.0)     # NewReno-style recovery: ssthresh + 3
    assert cc.cwnd_prior == pytest.approx(100.0)


def test_fast_convergence_lowers_wmax():
    cc = CubicCC(100, 50)
    cc.w_max = 120.0
    cc.on_dupack(info(ack=10, flight=100, snd_max=110), 3)
    assert cc.w_max == pytest.approx(100.0 * (1 + 0.7) / 2)
    cc2 = CubicCC(100, 50, fast_convergence=False)
    cc2.w_max = 120.0
    cc2.on_dupack(info(ack=10, flight=100, snd_max=110), 3)
    assert cc2.w_max == pytest.approx(100.0)


def test_congestion_avoidance_update_follows_target():
    cc = CubicCC(70, 70)
    cc.w_max = 100.0
    cc.cwnd_prior = 100.0
    # first CA ACK at t=10 s starts the epoch; growth uses W_cubic(t + RTT)
    cc.on_new_ack(info(ack=1, newly=1, now=10.0, srtt=0.1))
    assert cc.epoch_start == 10.0 and cc.cwnd_epoch == 70.0
    k = CubicCC.compute_k(100.0, 70.0, 0.4)
    assert cc.k == pytest.approx(k)
    # recompute the expected update by hand for the second ACK
    before = cc.cwnd
    w_est_before = cc.w_est
    t = 12.0 - 10.0
    w_t = 0.4 * (t - k) ** 3 + 100.0
    target = min(max(0.4 * (t + 0.1 - k) ** 3 + 100.0, before), 1.5 * before)
    w_est_after = w_est_before + cc.alpha_aimd * 1 / before
    cc.on_new_ack(info(ack=2, newly=1, now=12.0, srtt=0.1))
    if w_t < w_est_after:
        assert cc.cwnd == pytest.approx(max(before, w_est_after))
        assert cc.region == "reno_friendly"
    else:
        assert cc.cwnd == pytest.approx(before + (target - before) / before)
        assert cc.region == "concave"


def test_target_is_clamped_to_one_and_a_half_cwnd():
    cc = CubicCC(10, 10)
    cc.w_max, cc.cwnd_prior = 10.0, 10.0
    cc.on_new_ack(info(ack=1, newly=1, now=0.0, srtt=0.1))     # epoch starts, K = 0
    before = cc.cwnd
    cc.on_new_ack(info(ack=2, newly=1, now=100.0, srtt=0.1))   # W_cubic huge -> clamp
    assert cc.cwnd == pytest.approx(before + (1.5 * before - before) / before)
    assert cc.region == "convex"


def test_reno_friendly_region_when_cubic_is_slower():
    cc = CubicCC(50, 50)
    cc.w_max, cc.cwnd_prior = 50.5, 100.0
    cc.on_new_ack(info(ack=1, newly=1, now=0.0, srtt=0.1))
    cc.w_est = 60.0  # pretend Reno would already be at 60 segments
    cc.on_new_ack(info(ack=2, newly=1, now=0.01, srtt=0.1))
    assert cc.region == "reno_friendly"
    assert cc.cwnd >= 60.0


def test_timeout_sets_k_zero_for_next_epoch():
    cc = CubicCC(80, 50)
    cc.w_max = 120.0
    r = cc.on_timeout(info(ack=10, flight=80, snd_max=90))
    assert r.go_back_n
    assert cc.cwnd == 1.0 and cc.ssthresh == pytest.approx(56.0)
    assert cc.after_timeout
    cc.cwnd = 56.0  # slow start has brought cwnd back to ssthresh
    cc.on_new_ack(info(ack=11, newly=1, now=5.0))
    assert cc.k == 0.0 and cc.w_max == pytest.approx(56.0) and cc.cwnd_epoch == pytest.approx(56.0)


def test_cubic_end_to_end_plateaus_near_wmax_after_k_seconds():
    # long RTT (~200 ms) so the cubic function, not the Reno-friendly estimate, drives growth
    cfg = make_config("cubic", duration_s=20.0, bandwidth_mbps=50, delay_ms=100, initial_ssthresh=400,
                      buffer_packets=2000, forced_drops=(ForcedDrop(0, 6000),), cubic_fast_convergence=False)
    res = run_simulation(cfg)
    fr = res.events_of("fast_retransmit")
    assert len(fr) == 1 and res.flow_stats[0]["timeouts"] == 0
    exit_t = res.events_of("exit_recovery")["t"].iloc[0]
    cw = res.cwnd
    pre = cw[cw["t"] < fr["t"].iloc[0]]["cwnd"].iloc[-1]          # W_max (cwnd just before loss)
    ca = cw[(cw["t"] > exit_t) & (cw["phase"] == "congestion_avoidance")]
    epoch_start = ca["t"].iloc[0]
    epoch_cwnd = ca["cwnd"].iloc[0]
    k = CubicCC.compute_k(pre, epoch_cwnd, 0.4)
    at_k = cw[cw["t"] <= epoch_start + k]["cwnd"].iloc[-1]
    assert at_k == pytest.approx(pre, rel=0.06)                   # back near W_max after K seconds
    # concave approach: growth in the first second after the epoch is faster than in the second before K
    early = cw[cw["t"] <= epoch_start + 1.0]["cwnd"].iloc[-1] - epoch_cwnd
    late = at_k - cw[cw["t"] <= epoch_start + k - 1.0]["cwnd"].iloc[-1]
    assert early > late > 0
    assert not math.isnan(k) and k > 1.0
