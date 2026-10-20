"""TCP NewReno partial-ACK handling (RFC 6582)."""

import pytest

from algorithms.newreno import NewRenoCC
from config.validation import ForcedDrop, make_config
from simulator.engine import run_simulation
from tests.helpers import info


def enter(cc, ack=50, flight=20, snd_max=70):
    return cc.on_dupack(info(ack=ack, flight=flight, snd_max=snd_max), 3)


def test_entering_recovery_records_recover():
    cc = NewRenoCC(20, 64)
    r = enter(cc)
    assert r.retransmit_head and cc.in_recovery
    assert cc.recover == 69
    assert cc.ssthresh == pytest.approx(10.0) and cc.cwnd == pytest.approx(13.0)


def test_partial_ack_retransmits_and_stays_in_recovery():
    cc = NewRenoCC(20, 64)
    enter(cc)
    for n in range(4, 8):  # 4 more dup ACKs -> cwnd 17
        cc.on_dupack(info(ack=50, flight=20, snd_max=70), n)
    assert cc.cwnd == pytest.approx(17.0)
    r = cc.on_new_ack(info(ack=55, newly=5, flight=15, snd_max=70))
    assert cc.in_recovery
    assert r.retransmit_head and r.send_kind == "partial_retx"
    assert cc.cwnd == pytest.approx(17.0 - 5 + 1)   # deflate by newly acked, add back one SMSS
    assert r.restart_timer is True                   # first partial ACK resets the timer
    r2 = cc.on_new_ack(info(ack=58, newly=3, flight=12, snd_max=70))
    assert r2.retransmit_head and r2.restart_timer is False  # Impatient variant
    assert cc.partial_acks == 2


def test_slow_but_steady_variant_resets_timer_on_every_partial_ack():
    cc = NewRenoCC(20, 64, timer_variant="slow_but_steady")
    enter(cc)
    cc.on_new_ack(info(ack=55, newly=5, flight=15, snd_max=70))
    r2 = cc.on_new_ack(info(ack=58, newly=3, flight=12, snd_max=70))
    assert r2.restart_timer is True


def test_full_ack_exits_recovery():
    cc = NewRenoCC(20, 64)
    enter(cc)
    cc.on_new_ack(info(ack=55, newly=5, flight=15, snd_max=70))
    r = cc.on_new_ack(info(ack=70, newly=15, flight=4, snd_max=74))
    assert not cc.in_recovery
    assert cc.cwnd == pytest.approx(min(10.0, 4 + 1))  # RFC 6582 step 5 option 1
    assert r.events[0][0] == "exit_recovery" and not r.retransmit_head


def test_full_ack_with_large_flight_uses_ssthresh():
    cc = NewRenoCC(20, 64)
    enter(cc)
    cc.on_new_ack(info(ack=70, newly=20, flight=30, snd_max=100))
    assert cc.cwnd == pytest.approx(10.0)


def test_no_new_recovery_until_ack_passes_recover():
    cc = NewRenoCC(20, 64)
    enter(cc)  # recover = 69
    cc.on_new_ack(info(ack=70, newly=20, flight=4, snd_max=74))
    # duplicate ACKs whose cumulative ACK is <= recover cannot start a new recovery
    cc2 = NewRenoCC(20, 64)
    enter(cc2)
    cc2.in_recovery = False
    r = cc2.on_dupack(info(ack=60, flight=10, snd_max=70), 3)
    assert not r.retransmit_head
    # after the full ACK (ack 70 > recover 69) a new loss can be recovered
    r2 = cc.on_dupack(info(ack=70, flight=4, snd_max=74), 3)
    assert r2.retransmit_head and cc.in_recovery and cc.recover == 73


def test_newreno_three_losses_one_window_single_recovery_episode():
    cfg = make_config("newreno", duration_s=4.0, initial_ssthresh=32, buffer_packets=300,
                      forced_drops=(ForcedDrop(0, 200), ForcedDrop(0, 203), ForcedDrop(0, 206)))
    res = run_simulation(cfg)
    st = res.flow_stats[0]
    assert st["fast_retransmits"] == 1
    assert st["partial_acks"] == 2          # holes 203 and 206 are repaired by partial ACKs
    assert st["timeouts"] == 0
    assert st["recovery_episodes"] == 1
    sends = res.events_of("send")
    assert set(sends.loc[sends["info"] == "partial_retx", "seq"]) == {203, 206}
    # it exits only once, with a full ACK
    exits = res.events_of("exit_recovery")
    assert len(exits) == 1 and "full ACK" in exits.iloc[0]["info"]


def test_newreno_beats_reno_on_multiple_losses_in_one_window():
    drops = (ForcedDrop(0, 200), ForcedDrop(0, 203), ForcedDrop(0, 206))
    common = dict(duration_s=4.0, initial_ssthresh=32, buffer_packets=300, forced_drops=drops)
    reno = run_simulation(make_config("reno", **common)).flow_stats[0]
    newreno = run_simulation(make_config("newreno", **common)).flow_stats[0]
    assert newreno["fast_retransmits"] < reno["fast_retransmits"] + reno["timeouts"]
    assert newreno["delivered_segments"] >= reno["delivered_segments"]
