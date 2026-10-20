# Simulation assumptions, units and deliberate simplifications

This simulator models **selected TCP congestion-control mechanisms** at the segment level. It does not claim
full standards compliance; every simplification is listed here.

## Units

| Quantity | Unit | Notes |
|---|---|---|
| time | seconds (float) | RTT is *displayed* in ms |
| cwnd, ssthresh | segments (float) | one segment = one MSS-sized packet |
| sequence / ACK numbers | segments | ACK = next expected segment (cumulative) |
| bandwidth | Mbps in config, bit/s internally | |
| queue occupancy | packets *waiting* in the buffer | the packet being serialised is not counted |
| throughput / goodput | Mbps | 1 Mbps = 10^6 bit/s |
| loss | count and % | |

## Network model

* Dumbbell topology: N senders → one FIFO **drop-tail** buffer (`buffer_packets` waiting slots) → one bottleneck
  link (`bandwidth`, one-way propagation `delay`) → receivers.
* Access links are infinitely fast; a window increase releases back-to-back packets (no pacing).
* Serialization time = MSS × 8 / bandwidth (headers ignored: packet size = MSS).
* Base RTT = 2 × delay + one serialization time. BDP (packets) = bandwidth × base RTT / (8 × MSS).
* **ACK path**: propagation delay only; never queued, never lost.
* **Random loss** applies to **TCP data packets only**, decided when a packet finishes serialization (it
  consumed link capacity, then is lost on the wire). Loss bursts and scripted ("forced") drops are applied at
  the same point. Overflow drops happen on arrival at a full buffer. Every loss is logged with its cause.
* Optional unresponsive cross traffic (CBR or Poisson) shares the buffer; it is not subject to random loss and
  is counted in link utilisation, never in goodput.
* Randomness: `SeedSequence(seed)` spawns one stream per flow (loss draws) plus one for cross traffic.

## Event engine

Priority queue ordered by `(time, priority, insertion counter)`. Same-instant priority:
`LINK_TX_COMPLETE < DATA_ARRIVAL < ACK_ARRIVAL < RTO_EXPIRE < CROSS_ARRIVAL < FLOW_START < SAMPLE` — a link
frees capacity before new arrivals are queued, and an ACK arriving at the same instant as a timer expiry wins.
Runs stop at `duration_s` or `max_events`. Config validation rejects runs above ~400k bottleneck packets.

## Receiver

Cumulative ACK for **every** segment (no delayed ACKs), out-of-order buffering, duplicates discarded, no SACK,
fixed receive window (default 10,000 segments).

## Sender (common to all algorithms)

* Sends while `snd_nxt − snd_una < min(floor(cwnd), rwnd)`; infinite application backlog.
* Duplicate ACK = ACK equal to `snd_una` with data outstanding. Three trigger the algorithm's response.
* **RTO (RFC 6298)**: α = 1/8, β = 1/4, K = 4, G = 1 ms, initial 1 s, minimum 1 s (configurable; Linux uses 200 ms),
  maximum 60 s, exponential back-off, Karn's algorithm (no samples from retransmitted segments). Timer started on
  send when idle, restarted on new ACKs, stopped when everything is acknowledged.
* After a timeout the sender **goes back N** (resends from `snd_una`), as BSD-derived non-SACK stacks do.
* **Loss-response FlightSize**: `snd_max − snd_una` minus the segments that duplicate ACKs from an *earlier*
  hole showed to be at the receiver (Linux's non-SACK "duplicate-ACK SACK emulation"). For an isolated loss this
  equals RFC 5681 FlightSize exactly; it only differs after recovery episodes that sent new data, where the raw
  value would set ssthresh far above the path capacity.

## Algorithms

| | Growth | 3 dup ACKs | Timeout |
|---|---|---|---|
| Tahoe | SS +1/ACK, CA +1/cwnd | ssthresh = flight/2, cwnd = 1, go-back-N, `recover` guard | ssthresh = flight/2, cwnd = 1 |
| Reno (RFC 5681) | same | ssthresh = flight/2, cwnd = ssthresh+3, +1 per extra dup ACK, exit on *any* new ACK (cwnd = ssthresh) | same; `recover` set only here |
| NewReno (RFC 6582) | same | as Reno + `recover`; partial ACK: retransmit, cwnd −= newly acked −1, stay; full ACK: cwnd = min(ssthresh, max(flight,1)+1) | same; `recover` = highest sent |
| CUBIC (RFC 9438) | SS +1/ACK; CA: target = clamp(W(t+RTT), cwnd, 1.5 cwnd), cwnd += (target−cwnd)/cwnd, Reno-friendly W_est with α = 3(1−β)/(1+β) | W_max (fast convergence), ssthresh = 0.7 × flight, then NewReno recovery | ssthresh = 0.7 × flight, cwnd = 1, next epoch K = 0, W_max = cwnd_epoch |

CUBIC: C = 0.4, β = 0.7, `W(t) = C(t−K)³ + W_max`, `K = ∛((W_max − cwnd_epoch)/C)`; t from the start of the
congestion-avoidance epoch. No HyStart++.

NewReno/CUBIC timer on partial ACKs: **Impatient** (default, RFC 6582 §3.2 step 5) or **Slow-but-Steady**.

Fast-recovery **window inflation** follows the RFCs literally, so cwnd can reach very large values during long
recoveries; charts clip these spikes by default and say so.

## Metrics

See the docstring of `simulator/metrics.py`. Goodput counts unique in-order bytes delivered to the application;
link utilisation counts every serialised byte (≤ 100 % by construction); loss % = TCP drops / TCP transmissions;
RTT samples per ACK of a non-retransmitted segment; averages of cwnd and queue are time-weighted; Jain's index is
NaN (undefined) when all flows have zero goodput.

## Not modelled

SACK, delayed ACKs, connection setup/teardown, receiver window dynamics, Nagle, pacing, TSO, ECN, AQM (RED/CoDel),
BBR/Vegas, multi-hop paths, ACK loss, reordering, HyStart++, PRR.
