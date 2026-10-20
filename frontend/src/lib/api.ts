export type Algorithm = "tahoe" | "reno" | "newreno" | "cubic";
export const ALGORITHMS: Algorithm[] = ["tahoe", "reno", "newreno", "cubic"];
export const ALGO_LABEL: Record<string, string> = {
  tahoe: "Tahoe", reno: "Reno", newreno: "NewReno", cubic: "CUBIC",
};

export interface SimParams {
  algorithm: Algorithm;
  algorithms?: Algorithm[] | null;
  n_flows: number;
  flow_stagger_s: number;
  bandwidth_mbps: number;
  delay_ms: number;
  buffer_packets: number;
  loss_rate: number; // percent
  duration_s: number;
  seed: number;
  initial_ssthresh: number;
  cross_traffic_mbps: number;
  loss_burst_start_s?: number | null;
  timer_variant?: "impatient" | "slow_but_steady";
  playback?: boolean;
  playback_window_s?: number;
  playback_start_s?: number;
}

export const DEFAULT_PARAMS: SimParams = {
  algorithm: "reno", n_flows: 1, flow_stagger_s: 0, bandwidth_mbps: 10, delay_ms: 20, buffer_packets: 35,
  loss_rate: 0, duration_s: 20, seed: 42, initial_ssthresh: 64, cross_traffic_mbps: 0, loss_burst_start_s: null,
  timer_variant: "impatient", playback: true, playback_window_s: 3, playback_start_s: 0,
};

export interface Kpis {
  goodput_mbps: number; capacity_mbps: number; link_utilisation_pct: number; goodput_utilisation_pct: number;
  loss_pct: number; jain_index: number | null; packets_sent: number; packets_dropped: number;
  retransmissions: number; fast_retransmits: number; timeouts: number; avg_rtt_ms: number | null;
  base_rtt_ms: number; avg_cwnd: number | null; peak_cwnd: number | null; avg_queue_pkts: number | null;
  drops_by_cause: Record<string, number>;
}
export interface CwndSeries { flow: number; algorithm: Algorithm; points: [number, number, number][]; inflation_cap: number | null }
export interface EventItem {
  t: number; event: string; flow: number; seq: number; info: string; cwnd: number | null; ssthresh: number | null;
  queue: number; explanation: string; rule: string;
}
// [uid, flow, seq, kind, t_send, t_enq, t_tx0, t_tx1, t_rx, t_drop, cause]
export type PacketRow = [number, number, number, string, number, number | null, number | null, number | null, number | null, number | null, string | null];
export interface Playback {
  t0: number; t1: number; delay_s: number; tx_time_s: number; buffer_packets: number; n_flows: number; truncated: boolean;
  packets: PacketRow[]; acks: [number, number, number, number][];
  cwnd: [number, number, number, number, string][]; events: [number, string, number, number, string][];
}
export interface SimResult {
  run_id: string; config: any; bdp_packets: number; kpis: Kpis;
  flows: { flow: number; algorithm: Algorithm; goodput_mbps: number; loss_pct: number; fast_retransmits: number; timeouts: number; avg_rtt_ms: number | null; avg_cwnd: number | null }[];
  cwnd: CwndSeries[]; phases: { start: number; end: number; phase: string }[];
  queue: [number, number][]; rtt: [number, number, number][]; throughput: [number, number, number][];
  events: EventItem[]; events_total: number; playback: Playback | null; run_info: any;
}
export interface CompareRow {
  algorithm: Algorithm; goodput_mbps: number; link_util_pct: number; loss_pct: number; avg_rtt_ms: number | null;
  avg_queue_pkts: number | null; avg_cwnd: number | null; fast_retransmits: number; timeouts: number; retx_packets: number;
  median_regain_s: number | null; startup_s: number | null; jain_index: number | null;
}
export interface CompareResult { config: any; rows: CompareRow[]; cwnd: CwndSeries[]; notes: string[] }
export interface ScenarioInfo { id: string; title: string; summary: string; observe: string[]; fixed_algorithms: boolean; runs: string[] }
export interface Check { expectation: string; observed: string; status: "consistent" | "not observed" | "info" }
export interface ScenarioResult { id: string; title: string; checks: Check[]; runs: { label: string; config: any; kpis: Kpis; cwnd: CwndSeries[] }[] }
export interface PredictResult {
  available: boolean; message: string; horizon_s?: number; window_s?: number; model?: string; threshold?: number;
  points: [number, number, string, number | null][];
  peak?: { t: number; prob: number; risk: string; mean_prob: number; high_fraction: number };
  contributions: { feature: string; label: string; value: number; contribution: number }[];
  explanation: string; evaluation: Record<string, Record<string, number | null>>; importance: Record<string, number>;
  run_metrics?: Record<string, number | null> | null;
}
export interface ValidationResult {
  passed: number; failed: number; not_applicable: number;
  items: { scope: string; check: string; reference: string; status: string; detail: string }[];
  limitations: [string, string][]; audited_run: string;
}

export class ApiError extends Error {
  details: string[];
  constructor(msg: string, details: string[] = []) { super(msg); this.details = details; }
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, body === undefined ? undefined : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Cannot reach the API. Is the backend running on port 8000?");
  }
  if (!res.ok) {
    let details: string[] = [];
    try {
      const j = await res.json();
      if (j?.detail?.errors) details = j.detail.errors;
      else if (Array.isArray(j?.detail)) details = j.detail.map((d: any) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`);
      else if (typeof j?.detail === "string") details = [j.detail];
    } catch { /* ignore */ }
    throw new ApiError(res.status === 422 ? "Invalid configuration" : `Request failed (${res.status})`, details);
  }
  return res.json();
}

export const api = {
  simulate: (p: SimParams) => call<SimResult>("/api/simulate", p),
  compare: (p: SimParams, algs: Algorithm[]) => call<CompareResult>("/api/compare", { ...p, compare: algs, playback: false }),
  scenarios: () => call<ScenarioInfo[]>("/api/scenarios"),
  runScenario: (id: string, algorithm: Algorithm) => call<ScenarioResult>(`/api/scenarios/${id}/run`, { algorithm }),
  predict: (p: SimParams) => call<PredictResult>("/api/predict", { ...p, playback: false }),
  validation: () => call<ValidationResult>("/api/validation"),
  health: () => call<{ status: string; simulator_version: string }>("/api/health"),
};
