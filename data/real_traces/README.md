# Bundled real Linux traces

* Source: real Linux 6.18 kernel TCP (`reno`, `cubic`) via `iperf3 -C <alg> -t 15` over loopback.
* Bottleneck: `tc qdisc add dev lo root tbf rate 10mbit burst 32kbit limit 60000`, loopback MTU set to 1500 (MSS 1448).
* Sampling: `ss -tin` every 50 ms by `tools/capture_ss_trace.sh` (format documented there).
* Units: cwnd/ssthresh in segments, rtt/rttvar in ms (kernel SRTT, not per-ACK samples).
* Limitation: no propagation delay (RTT is queueing only); token bucket ≠ exact drop-tail; 50 ms sampling hides
  sub-interval events. Use for shape comparison only.
