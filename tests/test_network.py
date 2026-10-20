"""Bottleneck link, drop-tail buffer, receiver and RTO estimator unit tests."""

import pytest

from simulator.network import BottleneckLink, Receiver
from simulator.packets import DataPacket
from simulator.rto import RtoEstimator


def pkt(uid, seq=0, size=1500):
    return DataPacket(uid, 0, seq, size, 0.0, False, "new")


def test_link_serialization_time():
    link = BottleneckLink(10e6, 0.01, 5)
    assert link.tx_time(pkt(1)) == pytest.approx(1500 * 8 / 10e6)


def test_drop_tail_fifo():
    link = BottleneckLink(1e6, 0.01, 2)
    assert link.offer(pkt(1), 0.0) == "tx"        # straight into service
    assert link.offer(pkt(2), 0.0) == "queued"
    assert link.offer(pkt(3), 0.0) == "queued"
    assert link.occupancy == 2
    assert link.offer(pkt(4), 0.0) == "dropped"   # buffer full -> tail drop
    done, nxt = link.complete(0.012)
    assert done.uid == 1 and nxt.uid == 2 and nxt.tx_start_at == 0.012
    assert link.occupancy == 1
    assert link.offer(pkt(5), 0.013) == "queued"
    order = [link.complete(t)[0].uid for t in (0.024, 0.036, 0.048)]
    assert order == [2, 3, 5]
    assert not link.busy and link.occupancy == 0


def test_complete_without_packet_is_an_error():
    with pytest.raises(RuntimeError):
        BottleneckLink(1e6, 0.0, 1).complete(0.0)


def test_receiver_cumulative_ack_and_reassembly():
    r = Receiver(0)
    assert r.receive(0) == ("in_order", 1)
    assert r.receive(2) == ("out_of_order", 0)
    assert r.receive(3) == ("out_of_order", 0)
    assert r.rcv_nxt == 1                      # ACK stays at the hole -> duplicate ACKs
    assert r.receive(1) == ("in_order", 3)     # fills the hole, delivers 1,2,3
    assert r.rcv_nxt == 4
    assert r.receive(2) == ("duplicate", 0)    # retransmitted copy is not delivered again
    assert r.receive(5) == ("out_of_order", 0)
    assert r.receive(5) == ("duplicate", 0)
    assert r.delivered_segments == 4 and r.duplicates == 2


def test_rto_rfc6298_first_and_subsequent_samples():
    e = RtoEstimator(initial_rto=1.0, min_rto=0.2, max_rto=60.0, granularity=0.001)
    assert e.rto == 1.0
    e.update(0.1)
    assert e.srtt == pytest.approx(0.1) and e.rttvar == pytest.approx(0.05)
    assert e.rto == pytest.approx(0.1 + 4 * 0.05)
    e.update(0.2)
    rttvar = 0.75 * 0.05 + 0.25 * abs(0.1 - 0.2)
    srtt = 0.875 * 0.1 + 0.125 * 0.2
    assert e.rttvar == pytest.approx(rttvar) and e.srtt == pytest.approx(srtt)
    assert e.rto == pytest.approx(srtt + 4 * rttvar)


def test_rto_minimum_backoff_and_cap():
    e = RtoEstimator(initial_rto=1.0, min_rto=1.0, max_rto=8.0)
    e.update(0.05)
    assert e.rto == 1.0                         # rounded up to the minimum
    for expected in (2.0, 4.0, 8.0, 8.0):
        e.backoff()
        assert e.rto == expected
    e.update(0.05)                              # a fresh valid sample recomputes the RTO
    assert e.rto == 1.0 and e.backoffs == 0
