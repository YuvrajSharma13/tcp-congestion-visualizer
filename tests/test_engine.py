"""Event scheduler and end-to-end engine invariants."""

import numpy as np
import pytest

from config.validation import ConfigValidationError, ForcedDrop, LossBurst, SimulationConfig, make_config
from simulator.engine import Simulator, run_simulation
from simulator.events import EventQueue, EventType


# ------------------------------------------------------------------ scheduler
def test_events_pop_in_chronological_order():
    q = EventQueue()
    times = [5.0, 0.1, 3.3, 0.0, 2.2, 9.9, 0.05]
    for i, t in enumerate(times):
        q.push(t, EventType.SAMPLE, i)
    popped = [q.pop()[0] for _ in range(len(times))]
    assert popped == sorted(times)


def test_equal_time_events_use_priority_then_fifo():
    q = EventQueue()
    q.push(1.0, EventType.SAMPLE, "sample")
    q.push(1.0, EventType.RTO_EXPIRE, "rto-a")
    q.push(1.0, EventType.ACK_ARRIVAL, "ack")
    q.push(1.0, EventType.RTO_EXPIRE, "rto-b")
    q.push(1.0, EventType.LINK_TX_COMPLETE, "tx")
    order = [q.pop()[2] for _ in range(5)]
    assert order == ["tx", "ack", "rto-a", "rto-b", "sample"]


def test_invalid_event_time_rejected():
    q = EventQueue()
    with pytest.raises(ValueError):
        q.push(float("nan"), EventType.SAMPLE)
    with pytest.raises(ValueError):
        q.push(-1.0, EventType.SAMPLE)


# ----------------------------------------------------------- termination
def test_simulation_stops_at_configured_duration():
    res = run_simulation(make_config("reno", duration_s=2.5))
    assert res.run_info["termination"] == "duration_reached"
    for name in ("events", "cwnd", "rtt", "deliveries", "link", "samples"):
        df = getattr(res, name)
        assert df.empty or df["t"].max() <= 2.5 + 1e-12


def test_event_limit_is_enforced():
    res = run_simulation(make_config("reno", duration_s=20, max_events=5000))
    assert res.run_info["termination"] == "event_limit"
    assert res.run_info["events_processed"] == 5000


def test_event_times_never_decrease():
    res = run_simulation(make_config("newreno", n_flows=2, duration_s=3, loss_prob=0.01, buffer_packets=10))
    assert np.all(np.diff(res.events["t"].to_numpy()) >= 0)


# ------------------------------------------------------------------- timing
def test_first_rtt_equals_two_propagation_delays_plus_serialization():
    cfg = make_config("reno", duration_s=1.0, bandwidth_mbps=10, delay_ms=25, mss_bytes=1250)
    res = run_simulation(cfg)
    tx = 1250 * 8 / 10e6
    assert res.rtt["rtt_ms"].iloc[0] == pytest.approx((2 * 0.025 + tx) * 1000)
    assert cfg.base_rtt_s == pytest.approx(0.05 + tx)


def test_bandwidth_and_delay_change_timing():
    def first_rtt(**kw):
        return run_simulation(make_config("reno", duration_s=1.0, **kw)).rtt["rtt_ms"].iloc[0]

    assert first_rtt(delay_ms=50) - first_rtt(delay_ms=10) == pytest.approx(80.0)
    slow, fast = first_rtt(bandwidth_mbps=1), first_rtt(bandwidth_mbps=100)
    assert slow - fast == pytest.approx((1500 * 8 / 1e6 - 1500 * 8 / 100e6) * 1000)


def test_queueing_delay_appears_when_queue_builds():
    res = run_simulation(make_config("reno", duration_s=10, buffer_packets=100, initial_ssthresh=1000))
    base = res.config.base_rtt_s * 1000
    assert res.rtt["rtt_ms"].max() > base + 50 * res.config.tx_time_s * 1000


# ----------------------------------------------------------------- buffer
@pytest.mark.parametrize("alg", ["tahoe", "reno", "newreno", "cubic"])
@pytest.mark.parametrize("buf", [1, 5, 30])
def test_buffer_occupancy_never_exceeds_capacity(alg, buf):
    res = run_simulation(make_config(alg, n_flows=2, duration_s=4, buffer_packets=buf, initial_ssthresh=500))
    assert res.queue["queue"].max() <= buf
    assert res.queue["queue"].min() >= 0
    assert res.run_info["max_queue_seen"] <= buf
    assert res.run_info["overflow_drops_total"] > 0


# ----------------------------------------------------------- losses & logging
def test_every_drop_is_logged_with_its_cause():
    res = run_simulation(make_config("newreno", n_flows=2, duration_s=5, loss_prob=0.02, buffer_packets=8))
    drops = res.events_of("drop")
    assert len(drops) == sum(s["drops"] for s in res.flow_stats)
    causes = drops["info"].str.split(":").str[0]
    assert set(causes) <= {"overflow", "random", "burst", "forced"}
    assert (causes == "random").sum() == sum(s["drops_random"] for s in res.flow_stats)
    assert (causes == "overflow").sum() == sum(s["drops_overflow"] for s in res.flow_stats)


def test_every_retransmission_is_logged():
    res = run_simulation(make_config("reno", duration_s=5, loss_prob=0.02, record_packet_events=False))
    retx = res.events[(res.events["event"] == "send") & (res.events["info"] != "new")]
    assert len(retx) == res.flow_stats[0]["retx_packets"] > 0
    assert len(res.events_of("rx")) == 0  # per-packet events disabled, CC events kept
    assert len(res.events_of("fast_retransmit")) == res.flow_stats[0]["fast_retransmits"]


def test_random_loss_rate_matches_probability():
    res = run_simulation(make_config("cubic", duration_s=30, loss_prob=0.05, buffer_packets=1000,
                                     record_packet_events=False))
    st = res.flow_stats[0]
    tx_completed = len(res.link)
    rate = st["drops_random"] / tx_completed
    assert rate == pytest.approx(0.05, abs=0.01)


def test_forced_drop_hits_only_first_transmission():
    res = run_simulation(make_config("reno", duration_s=2, forced_drops=(ForcedDrop(0, 30),)))
    d = res.events_of("drop")
    assert list(d["seq"]) == [30] and d["info"].iloc[0] == "forced"
    assert res.flow_stats[0]["delivered_segments"] > 30


def test_loss_burst_causes_retransmission_timeout():
    res = run_simulation(make_config("newreno", duration_s=8, loss_bursts=(LossBurst(3.0, 0.5),)))
    st = res.flow_stats[0]
    assert st["drops_burst"] > 3 and st["timeouts"] >= 1
    to = res.events_of("timeout")
    assert (to["t"] > 3.0).all()
    after = res.cwnd[res.cwnd["t"] >= to["t"].iloc[0]].iloc[0]
    assert after["cwnd"] == 1.0


def test_timeouts_only_for_outstanding_data():
    res = run_simulation(make_config("tahoe", n_flows=2, duration_s=10, loss_prob=0.05, buffer_packets=4))
    to = res.events_of("timeout")
    assert len(to) > 0
    flights = to["info"].str.extract(r"flight=(\d+)")[0].astype(int)
    assert (flights > 0).all()


# --------------------------------------------------------------- delivery
@pytest.mark.parametrize("alg", ["tahoe", "reno", "newreno", "cubic"])
def test_delivered_data_is_never_counted_twice(alg):
    sim = Simulator(make_config(alg, n_flows=2, duration_s=6, loss_prob=0.02, buffer_packets=6))
    res = sim.run()
    for st, rcv, snd in zip(res.flow_stats, sim.receivers, sim.senders):
        f = st["flow"]
        delivered = int(res.deliveries.loc[res.deliveries["flow"] == f, "segments"].sum())
        assert delivered == rcv.rcv_nxt == st["delivered_segments"]
        assert delivered <= snd.snd_max
        assert snd.snd_una <= rcv.rcv_nxt     # sender never believes more was received than was
    total_retx = sum(s["retx_packets"] for s in res.flow_stats)
    assert total_retx > 0


def test_cumulative_acks_never_go_backwards():
    res = run_simulation(make_config("newreno", duration_s=5, loss_prob=0.03))
    rx = res.events_of("rx")
    acks = rx["info"].str.extract(r"ACK (\d+)")[0].astype(int).to_numpy()
    assert np.all(np.diff(acks) >= 0)


@pytest.mark.parametrize("alg", ["tahoe", "reno", "newreno", "cubic"])
def test_window_values_remain_valid(alg):
    res = run_simulation(make_config(alg, n_flows=3, duration_s=8, loss_prob=0.01, buffer_packets=10,
                                     initial_ssthresh=200))
    assert res.cwnd["cwnd"].min() >= 1.0
    assert res.cwnd["ssthresh"].min() >= 2.0
    assert np.isfinite(res.cwnd["cwnd"]).all()
    assert set(res.cwnd["phase"]) <= {"slow_start", "congestion_avoidance", "fast_recovery"}


def test_cross_traffic_shares_the_link():
    base = make_config("reno", duration_s=8, buffer_packets=50)
    from dataclasses import replace
    from config.validation import CrossTrafficConfig
    with_ct = replace(base, cross_traffic=CrossTrafficConfig(enabled=True, rate_mbps=4.0))
    a, b = run_simulation(base), run_simulation(with_ct)
    assert b.run_info["cross_sent"] > 0
    assert b.flow_stats[0]["delivered_segments"] < a.flow_stats[0]["delivered_segments"]
    cross_bytes = b.link.loc[b.link["flow"] == -1, "bytes"].sum()
    assert cross_bytes * 8 / 8.0 / 1e6 == pytest.approx(4.0, rel=0.05)


# ------------------------------------------------------------- validation
@pytest.mark.parametrize("kwargs, fragment", [
    (dict(bandwidth_mbps=0), "Bandwidth"),
    (dict(delay_ms=-5), "propagation delay"),
    (dict(buffer_packets=0), "Buffer capacity"),
    (dict(loss_prob=0.9), "loss probability"),
    (dict(duration_s=0), "duration"),
    (dict(mss_bytes=10), "MSS"),
    (dict(seed=-1), "seed"),
    (dict(newreno_timer_variant="sometimes"), "timer variant"),
    (dict(bandwidth_mbps=1000, duration_s=300), "packets through the bottleneck"),
])
def test_invalid_configurations_are_rejected(kwargs, fragment):
    with pytest.raises(ConfigValidationError) as exc:
        run_simulation(make_config("reno", **kwargs))
    assert any(fragment.lower() in e.lower() for e in exc.value.errors), exc.value.errors


def test_unknown_algorithm_and_bad_flow_settings_rejected():
    with pytest.raises(ConfigValidationError, match="unknown algorithm"):
        make_config("vegas").ensure_valid()
    with pytest.raises(ConfigValidationError, match="Number of flows"):
        make_config("reno", n_flows=11).ensure_valid()
    with pytest.raises(ConfigValidationError, match="does not exist"):
        make_config("reno", forced_drops=(ForcedDrop(3, 10),)).ensure_valid()
    with pytest.raises(ConfigValidationError, match="not before the end"):
        make_config("reno", flow_start_times=[30.0], duration_s=10).ensure_valid()


def test_validation_collects_all_errors():
    errs = SimulationConfig(bandwidth_mbps=-1, delay_ms=-1, buffer_packets=0).validate()
    assert len(errs) >= 3
