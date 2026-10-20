"""Learning Centre content.  Every statement matches the implemented model and cites its source."""

from __future__ import annotations

LESSONS: list[dict] = [
    {
        "id": "what",
        "title": "What congestion control is",
        "body": """
Many senders share the same links and router buffers. If together they send faster than the
**bottleneck** link can forward, packets pile up in the router's buffer (queueing delay grows) and,
once the buffer is full, new packets are **dropped**. Without a brake, senders retransmit the lost
data, the network carries more and more useless copies, and useful throughput collapses - the
"congestion collapse" of 1986 that led to Jacobson's 1988 algorithms.

TCP's brake is the **congestion window (cwnd)**: the sender may have at most cwnd segments in flight
(sent but not yet acknowledged). TCP raises cwnd while the network seems to have room and lowers it
when it sees a congestion signal - in this simulator, and in all four algorithms here, that signal is
**packet loss** (RFC 5681).
""",
        "try": {"algorithm": "reno", "duration_s": 10, "buffer_packets": 20},
    },
    {
        "id": "cwnd_rwnd",
        "title": "cwnd versus the receiver's window (rwnd)",
        "body": """
Two limits apply at once: the amount in flight may not exceed **min(cwnd, rwnd)**.

* **rwnd** (advertised receive window) is *flow control*: it protects the **receiver's** buffer and is
  announced by the receiver in every ACK.
* **cwnd** is *congestion control*: it protects the **network** and is the sender's private estimate.

In this simulator rwnd is a fixed cap (default 10,000 segments, adjustable under *Advanced*), so cwnd is
normally the binding limit. Set rwnd below the bandwidth-delay product and you will see goodput capped
even with no loss at all.
""",
        "try": {"algorithm": "reno", "duration_s": 10, "receiver_window": 15},
    },
    {
        "id": "ssthresh",
        "title": "ssthresh, slow start and congestion avoidance",
        "body": """
**ssthresh** (slow-start threshold) separates two growth modes (RFC 5681 §3.1):

* **Slow start** (cwnd < ssthresh): cwnd += 1 segment for every ACK of new data. One window of ACKs
  doubles cwnd, so growth is **exponential per RTT** - "slow" only because it starts from 1 segment.
* **Congestion avoidance** (cwnd >= ssthresh): cwnd += 1/cwnd per ACK, i.e. about **+1 segment per
  RTT** - linear, cautious probing.

After a loss, ssthresh is set to half of the data in flight (RFC 5681 eq. 4, minimum 2 segments), which
remembers "roughly where trouble started".
""",
        "try": {"algorithm": "newreno", "duration_s": 6, "initial_ssthresh": 16, "buffer_packets": 60},
    },
    {
        "id": "aimd",
        "title": "Additive increase, multiplicative decrease (AIMD)",
        "body": """
Reno-style TCP is **AIMD**: increase additively (+1 segment per RTT) and decrease multiplicatively
(halve on loss). Chiu and Jain showed AIMD is the combination that drives competing flows toward both
efficiency (full link) and fairness (equal shares). The result is the classic **sawtooth** cwnd curve.

CUBIC keeps the multiplicative decrease but with factor **beta = 0.7** instead of 0.5, and replaces the
additive increase with a cubic function of time (see *Algorithms compared*).
""",
        "try": {"algorithm": "reno", "duration_s": 20, "buffer_packets": 35},
    },
    {
        "id": "dupacks",
        "title": "Duplicate ACKs and fast retransmit",
        "body": """
The receiver sends a **cumulative ACK** carrying the next segment it expects. If segment 10 is lost but
11, 12, 13 arrive, each of them produces an ACK that still says "10" - **duplicate ACKs**.

One or two duplicate ACKs could just be reordering. **Three** duplicate ACKs are taken as evidence of
loss (RFC 5681 §3.2), and the sender **fast-retransmits** segment 10 immediately instead of waiting for
the retransmission timer. Tahoe then restarts slow start from cwnd = 1; Reno-family algorithms use fast
recovery.
""",
        "try": {"algorithm": "tahoe", "duration_s": 4, "buffer_packets": 200, "initial_ssthresh": 32,
                "forced_drops": [(0, 150)]},
    },
    {
        "id": "fastrec",
        "title": "Fast recovery (Reno) and partial ACKs (NewReno)",
        "body": """
**Reno** fast recovery (RFC 5681 §3.2): set ssthresh = FlightSize/2, retransmit, and set
cwnd = ssthresh + 3 (the three duplicate ACKs mean three segments left the network). Every further
duplicate ACK **inflates** cwnd by 1 so new data keeps flowing. The first ACK of new data **deflates**
cwnd to ssthresh and ends recovery.

If several segments of one window were lost, that first new ACK is only a **partial ACK**. Reno leaves
recovery anyway and must detect the next hole again (another halving) or wait for a timeout.

**NewReno** (RFC 6582) remembers `recover` = the highest segment sent when recovery began. A partial ACK
makes it retransmit the next hole at once and **stay** in recovery; only a full ACK covering `recover`
ends it. Note the large cwnd spikes during long recoveries in the charts: they are this inflation,
exactly as the RFCs specify.
""",
        "try": {"algorithm": "newreno", "duration_s": 6, "buffer_packets": 200, "initial_ssthresh": 32,
                "forced_drops": [(0, 300), (0, 303), (0, 306)]},
    },
    {
        "id": "rto",
        "title": "Retransmission timeout (RTO)",
        "body": """
If too few packets are in flight to generate three duplicate ACKs (for example after a burst of losses),
only the **retransmission timer** can detect the loss. RFC 6298 computes it from RTT samples:

* SRTT <- 7/8 SRTT + 1/8 R,  RTTVAR <- 3/4 RTTVAR + 1/4 |SRTT - R|
* RTO = SRTT + max(G, 4 RTTVAR), rounded up to at least **1 s** (configurable here; Linux uses 200 ms)

Samples from retransmitted segments are ignored (**Karn's algorithm**). When the timer fires the sender
retransmits, sets ssthresh to half the flight, drops cwnd to **1 segment**, and **doubles** the RTO
(exponential back-off). A timeout is the most expensive congestion response.
""",
        "try": {"algorithm": "reno", "duration_s": 10, "loss_bursts": [(4.0, 0.4)]},
    },
    {
        "id": "bdp",
        "title": "RTT, RTO and the bandwidth-delay product",
        "body": """
* **RTT** = 2 x propagation delay + serialization time + queueing delay. In this model the empty-queue
  (base) RTT is 2 x one-way delay + one packet's serialization time.
* **Bandwidth-delay product (BDP)** = bandwidth x RTT: the amount of data needed in flight to keep the
  link busy. In packets: BDP = bandwidth x base RTT / (8 x MSS).
* To fill the link, cwnd must reach about one BDP. Anything above BDP waits in the buffer, so the
  largest cwnd that avoids loss is about **BDP + buffer**. A buffer of about one BDP lets a halving
  Reno flow keep the link busy right after a loss.
""",
        "try": None,
    },
    {
        "id": "why",
        "title": "Why loss and queueing delay matter",
        "body": """
* **Loss** costs retransmissions and, more importantly, makes loss-based TCP shrink its window. Random
  (non-congestion) loss is misread as congestion: Reno's throughput falls roughly as
  MSS / (RTT x sqrt(p)) (Mathis et al., 1997). Try the *Increasing random loss* scenario.
* **Queueing delay** grows when buffers fill. Loss-based algorithms keep probing until the buffer
  overflows, so a large buffer can mean high latency for everyone ("bufferbloat"); a tiny buffer means
  frequent losses and an under-used link. The *Shallow buffer* scenario shows the trade-off.
""",
        "try": None,
    },
    {
        "id": "algos",
        "title": "Tahoe, Reno, NewReno and CUBIC compared",
        "body": """
| | Below ssthresh | Above ssthresh | 3 duplicate ACKs | Timeout |
|---|---|---|---|---|
| **Tahoe** | +1 per ACK | +1/cwnd per ACK | ssthresh = flight/2, cwnd = 1, slow start | ssthresh = flight/2, cwnd = 1 |
| **Reno** | +1 per ACK | +1/cwnd per ACK | fast retransmit + fast recovery, cwnd = ssthresh + 3; exits on any new ACK | same as Tahoe |
| **NewReno** | +1 per ACK | +1/cwnd per ACK | as Reno, but stays in recovery through partial ACKs until `recover` is acknowledged | same as Tahoe |
| **CUBIC** | +1 per ACK | W(t) = C(t - K)^3 + W_max, C = 0.4 | W_max = cwnd, ssthresh = 0.7 x flight (fast convergence lowers W_max) | ssthresh = 0.7 x flight, cwnd = 1 |

CUBIC grows quickly far below the previous maximum W_max, **flattens near W_max** (concave), then probes
faster beyond it (convex). Because growth depends on time, not on ACK arrivals, it is less penalised on
long-RTT paths. A Reno-friendly estimate keeps it at least as fast as Reno where Reno would be faster.
This simulator's CUBIC uses NewReno-style recovery and no HyStart++ (documented simplifications).
""",
        "try": None,
    },
]
