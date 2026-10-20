"""Typed, validated simulation configuration.

All configuration objects are frozen dataclasses so that a configuration can be
hashed, cached and reproduced exactly.  ``SimulationConfig.validate()`` returns
a list of human-readable problems; ``SimulationConfig.ensure_valid()`` raises
``ConfigValidationError`` containing all of them.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any

from config import defaults as D


class ConfigValidationError(ValueError):
    """Raised when a configuration cannot be simulated.  ``errors`` lists every problem."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("Invalid simulation configuration:\n- " + "\n- ".join(self.errors))


@dataclass(frozen=True)
class FlowConfig:
    """One bulk-transfer TCP flow (infinite application backlog)."""

    algorithm: str = "reno"
    start_time_s: float = 0.0
    initial_cwnd: float = D.DEFAULT_INITIAL_CWND
    initial_ssthresh: float = D.DEFAULT_INITIAL_SSTHRESH


@dataclass(frozen=True)
class CrossTrafficConfig:
    """Unresponsive (UDP-like) traffic sharing the bottleneck queue."""

    enabled: bool = False
    rate_mbps: float = 0.0
    start_time_s: float = 0.0
    stop_time_s: float | None = None
    pattern: str = "cbr"  # "cbr" (constant spacing) or "poisson" (exponential spacing)


@dataclass(frozen=True)
class LossBurst:
    """Every TCP data packet that finishes transmission in [start_s, start_s+duration_s) is lost."""

    start_s: float
    duration_s: float


@dataclass(frozen=True)
class ForcedDrop:
    """Drop the *first* transmission of segment ``seq`` of flow ``flow_id`` on the link."""

    flow_id: int
    seq: int


@dataclass(frozen=True)
class SimulationConfig:
    bandwidth_mbps: float = D.DEFAULT_BANDWIDTH_MBPS
    delay_ms: float = D.DEFAULT_DELAY_MS
    mss_bytes: int = D.DEFAULT_MSS_BYTES
    buffer_packets: int = D.DEFAULT_BUFFER_PACKETS
    loss_prob: float = D.DEFAULT_LOSS_PROB
    duration_s: float = D.DEFAULT_DURATION_S
    seed: int = D.DEFAULT_SEED
    flows: tuple[FlowConfig, ...] = field(default_factory=lambda: (FlowConfig(),))
    receiver_window: int = D.DEFAULT_RECEIVER_WINDOW
    initial_rto_s: float = D.DEFAULT_INITIAL_RTO_S
    min_rto_s: float = D.DEFAULT_MIN_RTO_S
    max_rto_s: float = D.DEFAULT_MAX_RTO_S
    clock_granularity_s: float = D.DEFAULT_CLOCK_GRANULARITY_S
    cubic_c: float = D.CUBIC_C
    cubic_beta: float = D.CUBIC_BETA
    cubic_fast_convergence: bool = True
    newreno_timer_variant: str = "impatient"  # RFC 6582 section 4: "impatient" or "slow_but_steady"
    cross_traffic: CrossTrafficConfig = field(default_factory=CrossTrafficConfig)
    loss_bursts: tuple[LossBurst, ...] = ()
    forced_drops: tuple[ForcedDrop, ...] = ()
    sample_interval_s: float = D.DEFAULT_SAMPLE_INTERVAL_S
    record_packet_events: bool = True
    max_events: int = D.DEFAULT_MAX_EVENTS

    # ------------------------------------------------------------------ derived
    @property
    def bandwidth_bps(self) -> float:
        return self.bandwidth_mbps * 1e6

    @property
    def one_way_delay_s(self) -> float:
        return self.delay_ms / 1000.0

    @property
    def tx_time_s(self) -> float:
        """Serialization time of one MSS-sized packet on the bottleneck."""
        return self.mss_bytes * 8.0 / self.bandwidth_bps

    @property
    def base_rtt_s(self) -> float:
        """Round-trip time with an empty queue: 2 x propagation + one serialization."""
        return 2.0 * self.one_way_delay_s + self.tx_time_s

    @property
    def bdp_packets(self) -> float:
        """Bandwidth-delay product (using the base RTT) in MSS-sized packets."""
        return self.bandwidth_bps * self.base_rtt_s / (8.0 * self.mss_bytes)

    @property
    def n_flows(self) -> int:
        return len(self.flows)

    @property
    def algorithms(self) -> tuple[str, ...]:
        return tuple(f.algorithm for f in self.flows)

    # --------------------------------------------------------------- validation
    def validate(self) -> list[str]:
        errs: list[str] = []
        L = D.LIMITS

        def rng(name: str, value: Any, lo: float, hi: float, unit: str = "") -> None:
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                errs.append(f"{name} must be a finite number (got {value!r}).")
            elif not (lo <= value <= hi):
                errs.append(f"{name} must be between {lo} and {hi}{unit} (got {value}).")

        rng("Bandwidth", self.bandwidth_mbps, *L["bandwidth_mbps"], " Mbps")
        if isinstance(self.bandwidth_mbps, (int, float)) and self.bandwidth_mbps <= 0:
            errs.append("Bandwidth must be greater than zero.")
        rng("One-way propagation delay", self.delay_ms, *L["delay_ms"], " ms")
        rng("MSS / packet size", self.mss_bytes, *L["mss_bytes"], " bytes")
        if not isinstance(self.mss_bytes, int) or isinstance(self.mss_bytes, bool):
            errs.append("MSS must be an integer number of bytes.")
        rng("Buffer capacity", self.buffer_packets, *L["buffer_packets"], " packets")
        if not isinstance(self.buffer_packets, int) or isinstance(self.buffer_packets, bool):
            errs.append("Buffer capacity must be an integer number of packets.")
        rng("Random loss probability", self.loss_prob, *L["loss_prob"])
        rng("Simulation duration", self.duration_s, *L["duration_s"], " s")
        rng("Random seed", self.seed, *L["seed"])
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            errs.append("Random seed must be an integer.")
        rng("Receiver window", self.receiver_window, *L["receiver_window"], " segments")
        rng("Sample interval", self.sample_interval_s, *L["sample_interval_s"], " s")
        rng("CUBIC C", self.cubic_c, 0.01, 10.0)
        rng("CUBIC beta", self.cubic_beta, 0.1, 0.95)
        rng("Initial RTO", self.initial_rto_s, 0.01, 60.0, " s")
        rng("Minimum RTO", self.min_rto_s, 0.001, 60.0, " s")
        rng("Maximum RTO", self.max_rto_s, 1.0, 600.0, " s")
        if not errs and self.min_rto_s > self.max_rto_s:
            errs.append("Minimum RTO cannot exceed maximum RTO.")
        rng("Event limit", self.max_events, 1000, L["max_events"])
        if self.newreno_timer_variant not in ("impatient", "slow_but_steady"):
            errs.append("NewReno timer variant must be 'impatient' or 'slow_but_steady'.")

        n = len(self.flows) if isinstance(self.flows, tuple) else -1
        if n < 0:
            errs.append("flows must be a tuple of FlowConfig objects.")
        elif not (L["flows"][0] <= n <= L["flows"][1]):
            errs.append(f"Number of flows must be between {L['flows'][0]} and {L['flows'][1]} (got {n}).")
        else:
            for i, f in enumerate(self.flows):
                tag = f"Flow {i}"
                if f.algorithm not in D.ALGORITHMS:
                    errs.append(f"{tag}: unknown algorithm {f.algorithm!r}; choose one of {', '.join(D.ALGORITHMS)}.")
                rng(f"{tag} initial cwnd", f.initial_cwnd, *L["initial_cwnd"], " segments")
                rng(f"{tag} initial ssthresh", f.initial_ssthresh, *L["initial_ssthresh"], " segments")
                rng(f"{tag} start time", f.start_time_s, 0.0, L["duration_s"][1], " s")
                if isinstance(f.start_time_s, (int, float)) and isinstance(self.duration_s, (int, float)) \
                        and f.start_time_s >= self.duration_s:
                    errs.append(f"{tag} starts at {f.start_time_s} s, which is not before the end of the simulation.")

        ct = self.cross_traffic
        if ct.enabled:
            if ct.pattern not in ("cbr", "poisson"):
                errs.append("Cross-traffic pattern must be 'cbr' or 'poisson'.")
            rng("Cross-traffic rate", ct.rate_mbps, 0.0, 1000.0, " Mbps")
            if isinstance(ct.rate_mbps, (int, float)) and ct.rate_mbps <= 0:
                errs.append("Cross-traffic rate must be greater than zero when cross traffic is enabled.")
            elif isinstance(ct.rate_mbps, (int, float)) and isinstance(self.bandwidth_mbps, (int, float)) \
                    and ct.rate_mbps >= self.bandwidth_mbps:
                errs.append("Cross-traffic rate must be lower than the bottleneck bandwidth, otherwise TCP is starved.")
            rng("Cross-traffic start", ct.start_time_s, 0.0, L["duration_s"][1], " s")
            if ct.stop_time_s is not None and ct.stop_time_s <= ct.start_time_s:
                errs.append("Cross-traffic stop time must be after its start time.")

        for b in self.loss_bursts:
            if b.start_s < 0 or b.duration_s <= 0:
                errs.append(f"Loss burst {b} must have start >= 0 and duration > 0.")
        for fd in self.forced_drops:
            if not (0 <= fd.flow_id < max(n, 0)):
                errs.append(f"Forced drop refers to flow {fd.flow_id}, which does not exist.")
            if fd.seq < 0:
                errs.append(f"Forced drop sequence number must be >= 0 (got {fd.seq}).")

        # Resource limits: keep the dashboard responsive.
        if not errs:
            est_packets = self.bandwidth_bps * self.duration_s / (8.0 * self.mss_bytes)
            if est_packets > L["max_link_packets"]:
                errs.append(
                    f"This run would push about {est_packets:,.0f} packets through the bottleneck "
                    f"(limit {L['max_link_packets']:,}). Reduce bandwidth or duration, or increase the MSS."
                )
            n_samples = self.duration_s / self.sample_interval_s
            if n_samples > L["max_samples"]:
                errs.append(
                    f"Sample interval {self.sample_interval_s} s over {self.duration_s} s gives "
                    f"{n_samples:,.0f} samples (limit {L['max_samples']:,}); increase the sample interval."
                )
        return errs

    def ensure_valid(self) -> "SimulationConfig":
        errs = self.validate()
        if errs:
            raise ConfigValidationError(errs)
        return self

    # ---------------------------------------------------------- serialisation
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["flows"] = [asdict(f) for f in self.flows]
        d["loss_bursts"] = [asdict(b) for b in self.loss_bursts]
        d["forced_drops"] = [asdict(x) for x in self.forced_drops]
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SimulationConfig":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ConfigValidationError([f"Unknown configuration field(s): {', '.join(sorted(unknown))}."])
        kw = dict(data)
        try:
            if "flows" in kw:
                kw["flows"] = tuple(FlowConfig(**f) for f in kw["flows"])
            if "cross_traffic" in kw and isinstance(kw["cross_traffic"], dict):
                kw["cross_traffic"] = CrossTrafficConfig(**kw["cross_traffic"])
            if "loss_bursts" in kw:
                kw["loss_bursts"] = tuple(LossBurst(**b) for b in kw["loss_bursts"])
            if "forced_drops" in kw:
                kw["forced_drops"] = tuple(ForcedDrop(**x) for x in kw["forced_drops"])
        except TypeError as exc:
            raise ConfigValidationError([f"Malformed configuration: {exc}"]) from exc
        return cls(**kw)

    @classmethod
    def from_json(cls, text: str) -> "SimulationConfig":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigValidationError([f"Configuration is not valid JSON: {exc}"]) from exc
        if isinstance(data, dict) and "config" in data and isinstance(data["config"], dict):
            data = data["config"]  # accept files written by reporting.export_json
        if not isinstance(data, dict):
            raise ConfigValidationError(["Configuration JSON must be an object."])
        return cls.from_dict(data)

    def with_algorithm(self, algorithm: str) -> "SimulationConfig":
        """Same network, every flow switched to ``algorithm`` (used for controlled comparisons)."""
        return replace(self, flows=tuple(replace(f, algorithm=algorithm) for f in self.flows))


def make_config(
    algorithm: str | list[str] = "reno",
    n_flows: int = 1,
    flow_start_times: list[float] | None = None,
    initial_cwnd: float = D.DEFAULT_INITIAL_CWND,
    initial_ssthresh: float = D.DEFAULT_INITIAL_SSTHRESH,
    **kwargs: Any,
) -> SimulationConfig:
    """Convenience constructor used by the UI, tests and ML data generation."""
    algs = [algorithm] * n_flows if isinstance(algorithm, str) else list(algorithm)
    starts = flow_start_times or [0.0] * len(algs)
    if len(starts) != len(algs):
        raise ConfigValidationError(["flow_start_times must have one entry per flow."])
    flows = tuple(
        FlowConfig(algorithm=a, start_time_s=float(s), initial_cwnd=initial_cwnd, initial_ssthresh=initial_ssthresh)
        for a, s in zip(algs, starts)
    )
    return SimulationConfig(flows=flows, **kwargs)
