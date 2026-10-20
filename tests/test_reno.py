"""TCP Reno fast retransmit / fast recovery (RFC 5681 section 3.2)."""

import pytest

from algorithms.reno import RenoCC
from config.validation import ForcedDrop, make_config
from simulator.engine import run_simulation
from tests.helpers import info


def test_enter_fast_recovery_on_third_dupack():
    cc = RenoCC(20, 64)
    cc.on_dupack(info(ack=50, flight=20), 1)
    cc.on_dupack(info(ack=50, flight=20), 2)
    r = cc.on_dupack(info(ack=50, flight=20), 3)
    assert r.retransmit_head and r.send_kind == "fast_retx"
    assert cc.in_recovery and cc.phase == "fast_recovery"
    assert cc.ssthresh == pytest.approx(10.0)
    assert cc.cwnd == pytest.approx(13.0)  # ssthresh + 3


def test_window_inflation_per_additional_dupack():
    cc = RenoCC(20, 64)
    cc.on_dupack(info(ack=50, flight=20), 3)
    for n in range(4, 9):
        cc.on_dupack(info(ack=50, flight=20), n)
    assert cc.cwnd == pytest.approx(13.0 + 5)


def test_exit_fast_recovery_on_new_ack_deflates_to_ssthresh():
    cc = RenoCC(20, 64)
    cc.on_dupack(info(ack=50, flight=20, snd_max=70), 3)
    cc.on_dupack(info(ack=50, flight=20, snd_max=70), 4)
    r = cc.on_new_ack(info(ack=70, newly=20, flight=0, snd_max=70))
    assert not cc.in_recovery
    assert cc.cwnd == pytest.approx(10.0)
    assert cc.phase == "congestion_avoidance"
    assert r.events and r.events[0][0] == "exit_recovery" and "full ACK" in r.events[0][1]


def test_partial_ack_also_exits_recovery_in_classic_reno():
    cc = RenoCC(20, 64)
    cc.on_dupack(info(ack=50, flight=20, snd_max=70), 3)
    r = cc.on_new_ack(info(ack=55, newly=5, flight=15, snd_max=70))
    assert not cc.in_recovery and cc.cwnd == pytest.approx(10.0)
    assert "partial ACK" in r.events[0][1]
    assert not r.retransmit_head  # Reno does not retransmit on a partial ACK


def test_reno_can_reenter_recovery_for_second_hole():
    """Classic Reno halves again for a second loss in the same window (no recover guard on FR)."""
    cc = RenoCC(20, 64)
    cc.on_dupack(info(ack=50, flight=20, snd_max=70), 3)
    cc.on_new_ack(info(ack=55, newly=5, flight=15, snd_max=70))
    r = cc.on_dupack(info(ack=55, flight=15, snd_max=70), 3)
    assert r.retransmit_head and cc.in_recovery
    assert cc.ssthresh == pytest.approx(7.5)


def test_timeout_during_recovery():
    cc = RenoCC(20, 64)
    cc.on_dupack(info(ack=50, flight=20, snd_max=70), 3)
    r = cc.on_timeout(info(ack=50, flight=20, snd_max=70))
    assert not cc.in_recovery and cc.cwnd == 1.0 and cc.ssthresh == 10.0
    assert r.go_back_n
    # after a timeout, duplicate ACKs for old data must not trigger a false fast retransmit
    r2 = cc.on_dupack(info(ack=60, flight=10, snd_max=70), 3)
    assert not r2.retransmit_head


def test_reno_end_to_end_single_loss():
    cfg = make_config("reno", duration_s=3.0, initial_ssthresh=16, buffer_packets=200,
                      forced_drops=(ForcedDrop(0, 60),))
    res = run_simulation(cfg)
    names = res.events["event"].tolist()
    assert names.count("fast_retransmit") == 1
    assert names.count("enter_recovery") == 1 and names.count("exit_recovery") == 1
    assert res.flow_stats[0]["timeouts"] == 0
    exit_row = res.events_of("exit_recovery").iloc[0]
    assert exit_row["cwnd"] == pytest.approx(exit_row["ssthresh"])
    # the recovery episode is visible as the fast_recovery phase in the cwnd trace
    assert (res.cwnd["phase"] == "fast_recovery").any()


def test_reno_multiple_losses_in_one_window_needs_more_than_one_recovery():
    cfg = make_config("reno", duration_s=4.0, initial_ssthresh=32, buffer_packets=300,
                      forced_drops=(ForcedDrop(0, 200), ForcedDrop(0, 203), ForcedDrop(0, 206)))
    res = run_simulation(cfg)
    st = res.flow_stats[0]
    assert st["partial_acks"] == 0
    assert st["fast_retransmits"] + st["timeouts"] >= 2
