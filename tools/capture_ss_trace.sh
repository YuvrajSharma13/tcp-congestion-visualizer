#!/usr/bin/env bash
# Capture a real Linux TCP trace (cwnd, ssthresh, rtt) with iperf3 + ss -ti.
#
# OPTIONAL - Linux or WSL2 only. The dashboard never runs this script and
# never changes your TCP stack; you run it yourself, then import the output
# file on the "Validation" page.
#
# Usage:
#   ./tools/capture_ss_trace.sh <server-ip> <duration_s> <algorithm> <outfile> [interval_s]
# Example (two terminals):
#   iperf3 -s                                   # on the server
#   ./tools/capture_ss_trace.sh 192.168.1.20 15 cubic trace_cubic.txt 0.05
#
# To emulate a bottleneck on the *sender's* interface (needs root, optional):
#   sudo tc qdisc add dev eth0 root netem delay 20ms rate 10mbit limit 40
#   ...capture...
#   sudo tc qdisc del dev eth0 root
#
# Output format: blocks of
#   # t=<unix seconds with fraction>
#   <the matching `ss -tin` lines for connections to the server's port 5201>
set -euo pipefail
SERVER=${1:?server ip}
DUR=${2:?duration seconds}
ALG=${3:-cubic}
OUT=${4:-trace.txt}
INTERVAL=${5:-0.05}

iperf3 -c "$SERVER" -t "$DUR" -C "$ALG" -i 0 >/dev/null &
PID=$!
: > "$OUT"
echo "# capture: iperf3 -c $SERVER -t $DUR -C $ALG, ss interval ${INTERVAL}s, host $(uname -sr)" >> "$OUT"
while kill -0 "$PID" 2>/dev/null; do
  echo "# t=$(date +%s.%N)" >> "$OUT"
  ss -tin "dst $SERVER and dport = :5201" >> "$OUT" 2>/dev/null || true
  sleep "$INTERVAL"
done
wait "$PID" || true
echo "wrote $OUT"
