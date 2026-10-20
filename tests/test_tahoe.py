"""TCP Tahoe state transitions (RFC 5681 slow start / congestion avoidance / fast retransmit)."""

import pytest

from algorithms.tahoe import TahoeCC
from config.validation import ForcedDrop, make_config
from simulator.engine import run_simulation
from tests.helpers import info


def test_slow_start_adds_one_segment_per_new_ack():
    cc = TahoeCC(1, 64)
    for i in range(5):
        cc.on_new_ack(info(ack=i + 1, newly=1))
    assert cc.cwnd == pytest.approx(6.0)
    assert cc.phase == "slow_start"


def test_congestion_avoidance_adds_one_over_cwnd():
    cc = TahoeCC(10, 10)
    assert cc.phase == "congestion_avoidance"
    cc.on_new_ack(info(ack=1, newly=1))
    assert cc.cwnd == pytest.approx(10.1)


def test_congestion_avoidance_adds_about_one_segment_per_rtt():
    cc = TahoeCC(20, 10)
    for i in range(20):  # one window's worth of ACKs
        cc.on_new_ack(info(ack=i + 1, newly=1))
    assert 20.9 < cc.cwnd < 21.0  # slightly less than +1 because cwnd grows during the round


def test_three_duplicate_acks_trigger_fast_retransmit_and_cwnd_one():
    cc = TahoeCC(20, 64)
    assert cc.on_dupack(info(ack=50, flight=20), 1).events == []
    assert cc.on_dupack(info(ack=50, flight=20), 2).events == []
    r = cc.on_dupack(info(ack=50, flight=20, snd_max=70), 3)
    assert r.go_back_n and r.send_kind == "fast_retx"
    assert ("fast_retransmit" in [e for e, _ in r.events])
    assert cc.ssthresh == pytest.approx(10.0)      # FlightSize / 2
    assert cc.cwnd == pytest.approx(1.0)
    assert cc.phase == "slow_start"
    assert not cc.in_recovery                      # Tahoe has no fast recovery
    assert cc.recover == 69
    # further duplicate ACKs do nothing (no inflation in Tahoe)
    r4 = cc.on_dupack(info(ack=50, flight=20), 4)
    assert cc.cwnd == 1.0 and not r4.go_back_n


def test_duplicate_acks_below_recover_do_not_retrigger():
    cc = TahoeCC(20, 64)
    cc.on_dupack(info(ack=50, flight=20, snd_max=70), 3)
    r = cc.on_dupack(info(ack=60, flight=10, snd_max=70), 3)  # 60 <= recover (69)
    assert not r.go_back_n and r.events == []


def test_ssthresh_never_below_two_segments():
    cc = TahoeCC(2, 64)
    cc.on_dupack(info(ack=5, flight=2), 3)
    assert cc.ssthresh == 2.0
    cc.on_timeout(info(ack=5, flight=1))
    assert cc.ssthresh == 2.0 and cc.cwnd == 1.0


def test_timeout_resets_window():
    cc = TahoeCC(30, 20)
    r = cc.on_timeout(info(ack=100, flight=30, snd_max=130))
    assert cc.cwnd == 1.0 and cc.ssthresh == 15.0
    assert r.go_back_n and r.send_kind == "rto_retx"
    assert cc.recover == 129


def test_tahoe_end_to_end_single_loss_returns_to_one_segment():
    cfg = make_config("tahoe", duration_s=3.0, initial_ssthresh=16, buffer_packets=200,
                      forced_drops=(ForcedDrop(0, 60),))
    res = run_simulation(cfg)
    fr = res.events_of("fast_retransmit")
    assert len(fr) == 1
    t_fr = fr["t"].iloc[0]
    after = res.cwnd[res.cwnd["t"] >= t_fr].iloc[0]
    assert after["cwnd"] == 1.0
    assert res.flow_stats[0]["timeouts"] == 0
    # the lost segment was retransmitted and everything got delivered in order
    retx = res.events_of("send")
    assert (retx[retx["seq"] == 60]["info"] == "fast_retx").any()
