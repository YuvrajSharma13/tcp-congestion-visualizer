"""Default values, limits and constants shared across the project.

Units used throughout the code base (see docs/simulation_assumptions.md):

* time            -> seconds (float) internally; RTT is *displayed* in ms
* cwnd / ssthresh -> segments (float), one segment = one MSS-sized packet
* bandwidth       -> Mbps in configuration, bits/s internally
* queue occupancy -> packets waiting in the bottleneck buffer
* throughput      -> Mbps
"""

from __future__ import annotations

SIMULATOR_VERSION = "1.0.0"
"""Bumped whenever simulator behaviour changes in a way that alters results."""

CONFIG_SCHEMA_VERSION = 1
"""Version of the JSON configuration format written by reporting/export_json.py."""

ALGORITHMS: tuple[str, ...] = ("tahoe", "reno", "newreno", "cubic")
ALGORITHM_LABELS: dict[str, str] = {
    "tahoe": "TCP Tahoe",
    "reno": "TCP Reno",
    "newreno": "TCP NewReno",
    "cubic": "TCP CUBIC",
}

# --- Network defaults ---------------------------------------------------------
DEFAULT_BANDWIDTH_MBPS = 10.0
DEFAULT_DELAY_MS = 20.0          # one-way propagation delay
DEFAULT_MSS_BYTES = 1500
DEFAULT_BUFFER_PACKETS = 40
DEFAULT_LOSS_PROB = 0.0          # probability in [0, 1]
DEFAULT_DURATION_S = 20.0
DEFAULT_SEED = 42

# --- TCP defaults --------------------------------------------------------------
DEFAULT_INITIAL_CWND = 1.0       # segments (RFC 5681 allows up to 4, RFC 6928 allows 10)
DEFAULT_INITIAL_SSTHRESH = 64.0  # segments ("arbitrarily high" per RFC 5681; finite for clarity)
DEFAULT_RECEIVER_WINDOW = 10_000 # segments; large so cwnd is normally the binding limit
DUPACK_THRESHOLD = 3             # RFC 5681 section 3.2

# --- RFC 6298 retransmission timer ----------------------------------------------
RTO_ALPHA = 1.0 / 8.0
RTO_BETA = 1.0 / 4.0
RTO_K = 4.0
DEFAULT_INITIAL_RTO_S = 1.0      # RFC 6298 (2.1)
DEFAULT_MIN_RTO_S = 1.0          # RFC 6298 (2.4) "SHOULD be rounded up to 1 second"
DEFAULT_MAX_RTO_S = 60.0         # RFC 6298 (2.5) allows an upper bound of at least 60 s
DEFAULT_CLOCK_GRANULARITY_S = 0.001

# --- CUBIC (RFC 9438) ------------------------------------------------------------
CUBIC_C = 0.4                    # RFC 9438 section 5.1
CUBIC_BETA = 0.7                 # RFC 9438 section 4.6

# --- Recording ------------------------------------------------------------------
DEFAULT_SAMPLE_INTERVAL_S = 0.01

# --- Validation limits (keep the dashboard responsive on a laptop) ---------------
LIMITS = {
    "bandwidth_mbps": (0.01, 1000.0),
    "delay_ms": (0.0, 2000.0),
    "mss_bytes": (64, 9000),
    "buffer_packets": (1, 10_000),
    "loss_prob": (0.0, 0.5),
    "duration_s": (0.1, 300.0),
    "flows": (1, 10),
    "seed": (0, 2**32 - 1),
    "initial_cwnd": (1.0, 1000.0),
    "initial_ssthresh": (2.0, 1_000_000.0),
    "receiver_window": (1, 1_000_000),
    "sample_interval_s": (0.001, 1.0),
    "max_samples": 60_000,
    "max_link_packets": 400_000,
    "max_events": 5_000_000,
}

DEFAULT_MAX_EVENTS = 3_000_000
