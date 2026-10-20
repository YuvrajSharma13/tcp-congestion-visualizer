"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Algorithm = Literal["tahoe", "reno", "newreno", "cubic"]


# ------------------------------------------------------------------ requests
class SimulateRequest(BaseModel):
    algorithm: Algorithm = "reno"
    algorithms: Optional[list[Algorithm]] = Field(
        None, description="Per-flow algorithms; overrides `algorithm` and `n_flows` when given")
    n_flows: int = Field(1, ge=1, le=10)
    flow_stagger_s: float = Field(0.0, ge=0, le=60, description="Flow i starts at i x stagger")
    bandwidth_mbps: float = Field(10.0, gt=0, le=1000)
    delay_ms: float = Field(20.0, ge=0, le=2000, description="One-way propagation delay")
    buffer_packets: int = Field(35, ge=1, le=10000)
    loss_rate: float = Field(0.0, ge=0, le=50, description="Random loss on data packets, in PERCENT")
    duration_s: float = Field(20.0, gt=0, le=300)
    seed: int = Field(42, ge=0, le=2**32 - 1)
    mss_bytes: int = Field(1500, ge=64, le=9000)
    initial_cwnd: float = Field(1.0, ge=1, le=1000)
    initial_ssthresh: float = Field(64.0, ge=2, le=1e6)
    cross_traffic_mbps: float = Field(0.0, ge=0, le=1000, description="0 disables cross traffic")
    loss_burst_start_s: Optional[float] = Field(None, ge=0)
    loss_burst_ms: float = Field(400.0, gt=0, le=10000)
    min_rto_ms: float = Field(1000.0, ge=1, le=60000)
    timer_variant: Literal["impatient", "slow_but_steady"] = "impatient"
    playback: bool = Field(True, description="Include the packet-level trace for the canvas")
    playback_window_s: float = Field(3.0, gt=0, le=30)
    playback_start_s: float = Field(0.0, ge=0)


class CompareRequest(SimulateRequest):
    compare: list[Algorithm] = Field(default_factory=lambda: ["tahoe", "reno", "newreno", "cubic"], min_length=1)
    playback: bool = False


class ScenarioRunRequest(BaseModel):
    algorithm: Algorithm = "reno"


# ----------------------------------------------------------------- responses
class Kpis(BaseModel):
    goodput_mbps: float
    capacity_mbps: float
    link_utilisation_pct: float
    goodput_utilisation_pct: float
    loss_pct: float
    jain_index: Optional[float]
    packets_sent: int
    packets_dropped: int
    retransmissions: int
    fast_retransmits: int
    timeouts: int
    avg_rtt_ms: Optional[float]
    base_rtt_ms: float
    avg_cwnd: Optional[float]
    peak_cwnd: Optional[float]
    avg_queue_pkts: Optional[float]
    drops_by_cause: dict[str, int]


class FlowKpi(BaseModel):
    flow: int
    algorithm: str
    goodput_mbps: float
    loss_pct: float
    fast_retransmits: int
    timeouts: int
    avg_rtt_ms: Optional[float]
    avg_cwnd: Optional[float]


class CwndPoint(BaseModel):
    t: float
    cwnd: float
    ssthresh: float


class CwndSeries(BaseModel):
    flow: int
    algorithm: str
    points: list[list[float]] = Field(description="[t, cwnd, ssthresh] step points")
    inflation_cap: Optional[float] = Field(None, description="Suggested y max hiding fast-recovery inflation")


class PhaseSpan(BaseModel):
    start: float
    end: float
    phase: str


class EventItem(BaseModel):
    t: float
    event: str
    flow: int
    seq: int
    info: str
    cwnd: Optional[float]
    ssthresh: Optional[float]
    queue: int
    explanation: str
    rule: str


class Playback(BaseModel):
    t0: float
    t1: float
    delay_s: float
    tx_time_s: float
    buffer_packets: int
    n_flows: int
    truncated: bool
    packets: list[list] = Field(description="[uid, flow, seq, kind, t_send, t_enq, t_tx0, t_tx1, t_rx, t_drop, cause]")
    acks: list[list] = Field(description="[flow, ack, t_send, t_arrive]")
    cwnd: list[list] = Field(description="[t, flow, cwnd, ssthresh, phase]")
    events: list[list] = Field(description="[t, event, flow, seq, info] congestion events in window")


class SimulateResponse(BaseModel):
    run_id: str
    config: dict
    bdp_packets: float
    kpis: Kpis
    flows: list[FlowKpi]
    cwnd: list[CwndSeries]
    phases: list[PhaseSpan]
    queue: list[list[float]]
    rtt: list[list[float]] = Field(description="[t, flow, rtt_ms]")
    throughput: list[list[float]] = Field(description="[t_mid, flow, goodput_mbps]")
    events: list[EventItem]
    events_total: int
    playback: Optional[Playback]
    run_info: dict


class CompareRow(BaseModel):
    algorithm: str
    goodput_mbps: float
    link_util_pct: float
    loss_pct: float
    avg_rtt_ms: Optional[float]
    avg_queue_pkts: Optional[float]
    avg_cwnd: Optional[float]
    fast_retransmits: int
    timeouts: int
    retx_packets: int
    median_regain_s: Optional[float]
    startup_s: Optional[float]
    jain_index: Optional[float]


class CompareResponse(BaseModel):
    config: dict
    rows: list[CompareRow]
    cwnd: list[CwndSeries]
    notes: list[str]


class ScenarioInfo(BaseModel):
    id: str
    title: str
    summary: str
    observe: list[str]
    fixed_algorithms: bool
    runs: list[str]


class CheckItem(BaseModel):
    expectation: str
    observed: str
    status: Literal["consistent", "not observed", "info"]


class ScenarioRunItem(BaseModel):
    label: str
    config: dict
    kpis: Kpis
    cwnd: list[CwndSeries]


class ScenarioRunResponse(BaseModel):
    id: str
    title: str
    checks: list[CheckItem]
    runs: list[ScenarioRunItem]


class Contribution(BaseModel):
    feature: str
    label: str
    value: float
    contribution: float


class PredictResponse(BaseModel):
    available: bool
    message: str
    horizon_s: Optional[float] = None
    window_s: Optional[float] = None
    model: Optional[str] = None
    threshold: Optional[float] = None
    points: list[list] = Field(default_factory=list, description="[t, prob, risk, actual]")
    peak: Optional[dict] = None
    contributions: list[Contribution] = Field(default_factory=list)
    explanation: str = ""
    evaluation: dict = Field(default_factory=dict)
    importance: dict[str, float] = Field(default_factory=dict)
    run_metrics: Optional[dict] = None


class ValidationItem(BaseModel):
    scope: str
    check: str
    reference: str
    status: str
    detail: str


class ValidationResponse(BaseModel):
    passed: int
    failed: int
    not_applicable: int
    items: list[ValidationItem]
    limitations: list[list[str]]
    audited_run: str
