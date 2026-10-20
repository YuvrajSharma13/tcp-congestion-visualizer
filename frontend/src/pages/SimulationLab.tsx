import { useMemo, useState } from "react";
import clsx from "clsx";
import { BookOpen, FlaskConical, Play, RotateCcw, SlidersHorizontal, Zap } from "lucide-react";
import type { SimState } from "../App";
import { ALGO_LABEL, DEFAULT_PARAMS, type Algorithm, type EventItem } from "../lib/api";
import { fmt, int } from "../lib/format";
import { ALGO_COLOR, C, EVENT_LABEL, STATUS, flowColor } from "../lib/theme";
import { CwndChart, QueueChart, RttChart } from "../components/charts";
import { AlgoDot, AlgoPicker, Badge, Card, Empty, ErrorBox, Kpi, Modal, Slider, Spinner } from "../components/ui";

export function ConfigPanel({ s, compact = false }: { s: SimState; compact?: boolean }) {
  const { params: p, setParams } = s;
  const set = (k: keyof typeof p) => (v: any) => setParams({ ...p, [k]: v });
  const baseRtt = 2 * p.delay_ms + (1500 * 8) / (p.bandwidth_mbps * 1e3);
  const bdp = (p.bandwidth_mbps * 1e6 * baseRtt) / 1000 / (8 * 1500);
  const [adv, setAdv] = useState(false);
  return (
    <div className="space-y-5">
      {!compact && (
        <div>
          <div className="label mb-2">Algorithm</div>
          <AlgoPicker value={p.algorithm} onChange={(a) => setParams({ ...p, algorithm: a, algorithms: null })} />
        </div>
      )}
      <Slider label="Bottleneck bandwidth" unit="Mbps" value={p.bandwidth_mbps} min={0.5} max={200} step={0.5} log
        onChange={set("bandwidth_mbps")} help="Capacity of the shared link" />
      <Slider label="One-way delay" unit="ms" value={p.delay_ms} min={1} max={500} step={1} log onChange={set("delay_ms")} />
      <Slider label="Buffer size" unit="pkts" value={p.buffer_packets} min={1} max={500} step={1} log onChange={set("buffer_packets")} />
      <Slider label="Random loss" unit="%" value={p.loss_rate} min={0} max={5} step={0.05} onChange={set("loss_rate")}
        format={(v) => v.toFixed(2)} help="Applied to data packets on the link; ACKs are never lost" />
      <Slider label="Duration" unit="s" value={p.duration_s} min={2} max={60} step={1} onChange={set("duration_s")} />
      <Slider label="Competing flows" value={p.n_flows} min={1} max={6} step={1}
        onChange={(v) => setParams({ ...p, n_flows: v, algorithms: null, flow_stagger_s: v > 1 ? p.flow_stagger_s || 2 : 0 })} />
      {p.n_flows > 1 && (
        <Slider label="Start stagger between flows" unit="s" value={p.flow_stagger_s} min={0} max={10} step={0.5} onChange={set("flow_stagger_s")} />
      )}
      <div className="rounded-lg border border-ink-600 bg-ink-900/70 p-3 text-xs leading-relaxed text-fg-2">
        <div className="mb-1 flex items-center gap-1.5 font-medium text-fg"><Zap size={13} className="text-amber" />Bandwidth-delay product</div>
        {p.bandwidth_mbps} Mbps × {baseRtt.toFixed(1)} ms = <b className="tnum text-fg">{bdp.toFixed(1)} pkts</b>.
        Buffer = <b className="tnum text-fg">{(p.buffer_packets / Math.max(bdp, 1e-9)).toFixed(2)}×</b> BDP · losses begin near cwnd ≈ {(bdp + p.buffer_packets + 1).toFixed(0)}.
      </div>
      <button className="flex w-full items-center gap-2 text-xs text-fg-3 hover:text-fg-2" onClick={() => setAdv(!adv)}>
        <SlidersHorizontal size={13} /> Advanced {adv ? "▴" : "▾"}
      </button>
      {adv && (
        <div className="space-y-4">
          <Slider label="Initial ssthresh" unit="seg" value={p.initial_ssthresh} min={2} max={2000} step={1} log onChange={set("initial_ssthresh")} />
          <Slider label="Cross traffic" unit="Mbps" value={p.cross_traffic_mbps} min={0} max={Math.max(0, p.bandwidth_mbps * 0.9)}
            step={0.1} onChange={set("cross_traffic_mbps")} format={(v) => v.toFixed(1)} />
          <label className="flex items-center justify-between text-xs text-fg-2">
            Loss burst at 5 s (400 ms)
            <input type="checkbox" checked={p.loss_burst_start_s != null}
              onChange={(e) => setParams({ ...p, loss_burst_start_s: e.target.checked ? 5 : null })} />
          </label>
          <label className="flex items-center justify-between text-xs text-fg-2">
            NewReno/CUBIC partial-ACK timer
            <select className="rounded border border-ink-600 bg-ink-900 px-1.5 py-1 text-fg" value={p.timer_variant}
              onChange={(e) => setParams({ ...p, timer_variant: e.target.value as any })}>
              <option value="impatient">Impatient (RFC 6582)</option>
              <option value="slow_but_steady">Slow-but-Steady</option>
            </select>
          </label>
          {p.n_flows > 1 && (
            <div>
              <div className="mb-1.5 text-xs text-fg-2">Per-flow algorithms</div>
              <div className="flex flex-wrap gap-1.5">
                {Array.from({ length: p.n_flows }, (_, i) => {
                  const algs = p.algorithms ?? Array(p.n_flows).fill(p.algorithm);
                  return (
                    <select key={i} value={algs[i]} className="rounded border border-ink-600 bg-ink-900 px-1.5 py-1 text-xs text-fg"
                      style={{ borderColor: flowColor(i) }}
                      onChange={(e) => { const n = [...algs]; n[i] = e.target.value as Algorithm; setParams({ ...p, algorithms: n }); }}>
                      {(["tahoe", "reno", "newreno", "cubic"] as Algorithm[]).map((a) => <option key={a} value={a}>F{i} {ALGO_LABEL[a]}</option>)}
                    </select>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function pctDelta(a?: number | null, b?: number | null) {
  if (a == null || b == null || b === 0) return null;
  return ((a - b) / Math.abs(b)) * 100;
}

export default function SimulationLab({ s }: { s: SimState }) {
  const { sim, prev, loading, error, run, setParams } = s;
  const [clip, setClip] = useState(true);
  const [sel, setSel] = useState<EventItem | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const sameNet = prev && sim && prev.config.bandwidth_mbps === sim.config.bandwidth_mbps;
  const k = sim?.kpis;
  const feed = useMemo(() => (sim?.events ?? []).filter((e) => e.event !== "phase_change" && (filter === "all" || e.event === filter)), [sim, filter]);
  const kinds = useMemo(() => Array.from(new Set((sim?.events ?? []).map((e) => e.event))).filter((e) => e !== "phase_change"), [sim]);

  return (
    <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
      <aside className="space-y-4 lg:sticky lg:top-[120px] lg:self-start">
        <Card title="Network & TCP" subtitle="Drag to configure; values are validated by the backend"
          right={<button className="text-fg-3 hover:text-fg" title="Reset" onClick={() => setParams(DEFAULT_PARAMS)}><RotateCcw size={15} /></button>}>
          <ConfigPanel s={s} />
          <button className="btn-primary mt-5 w-full" onClick={() => run()} disabled={loading}>
            {loading ? <Spinner label="Simulating…" /> : <><Play size={15} />Run simulation</>}
          </button>
        </Card>
      </aside>

      <div className="min-w-0 space-y-5">
        <ErrorBox error={error} />
        {!sim && !loading && (
          <Empty icon={<FlaskConical size={22} />} title="No simulation yet">
            Configure the bottleneck on the left and press <b>Run simulation</b>. Nothing on this page is shown until a real run exists.
          </Empty>
        )}
        {!sim && loading && <div className="card grid h-80 place-items-center"><Spinner label="Running the discrete-event engine…" /></div>}
        {sim && k && (
          <>
            <div className="flex flex-wrap items-center gap-2 text-xs text-fg-3">
              <span className="font-mono text-fg-2">{sim.run_id}</span>
              {Array.from(new Set(sim.flows.map((f) => f.algorithm))).map((a) => (
                <span key={a} className="inline-flex items-center gap-1.5 rounded-full border border-ink-600 px-2 py-0.5 text-fg-2"><AlgoDot algorithm={a} />{ALGO_LABEL[a]}</span>
              ))}
              <span>{sim.config.bandwidth_mbps} Mbps · {sim.config.delay_ms} ms · buffer {sim.config.buffer_packets} · loss {(sim.config.loss_prob * 100).toFixed(2)}% · seed {sim.config.seed}</span>
              <span className="ml-auto">{int(sim.run_info.events_processed)} events · {fmt(sim.run_info.wall_time_s, 2)} s</span>
            </div>
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <Kpi label="Goodput" value={fmt(k.goodput_mbps, 2, " Mbps")} hint={`of ${k.capacity_mbps} Mbps capacity`} accent={C.blue}
                delta={sameNet ? pctDelta(k.goodput_mbps, prev!.kpis.goodput_mbps) : null} />
              <Kpi label="Link utilisation" value={fmt(k.link_utilisation_pct, 1, "%")} hint="bytes serialised / capacity" accent={C.emerald}
                delta={sameNet ? pctDelta(k.link_utilisation_pct, prev!.kpis.link_utilisation_pct) : null} />
              <Kpi label="Loss rate" value={fmt(k.loss_pct, 2, "%")} hint={`${int(k.packets_dropped)} of ${int(k.packets_sent)} packets dropped`} accent={C.ruby}
                delta={prev ? pctDelta(k.loss_pct, prev.kpis.loss_pct) : null} />
              <Kpi label="Jain's fairness" value={k.jain_index == null ? "—" : fmt(k.jain_index, 3)} accent={C.violet}
                hint={k.jain_index == null ? "single flow" : `${sim.flows.length} flows · 1 = equal shares`} />
            </div>
            <div className="grid grid-cols-2 gap-3 text-xs md:grid-cols-5">
              {[["Avg RTT", fmt(k.avg_rtt_ms, 1, " ms"), `base ${fmt(k.base_rtt_ms, 1)} ms`],
                ["Fast retransmits", int(k.fast_retransmits), `${int(k.retransmissions)} retransmitted`],
                ["Timeouts", int(k.timeouts), "RTO expiries"],
                ["Avg / peak cwnd", `${fmt(k.avg_cwnd, 1)} / ${fmt(k.peak_cwnd, 0)}`, "segments"],
                ["Avg queue", fmt(k.avg_queue_pkts, 1, " pkts"), `BDP ${fmt(sim.bdp_packets, 1)} pkts`]].map(([l, v, h]) => (
                <div key={l} className="rounded-lg border border-ink-600 bg-ink-850 px-3 py-2">
                  <div className="text-fg-3">{l}</div><div className="tnum text-base font-semibold text-fg">{v}</div><div className="text-fg-3">{h}</div>
                </div>
              ))}
            </div>

            <Card title="Congestion window & ssthresh" subtitle="Solid = cwnd, dashed = ssthresh. Click any marker for the RFC rule behind it."
              right={
                <div className="flex items-center gap-3 text-xs text-fg-3">
                  {sim.cwnd.length === 1 && <>
                    <span className="flex items-center gap-1"><span className="h-2.5 w-3 rounded-sm bg-blue/30" />slow start</span>
                    <span className="flex items-center gap-1"><span className="h-2.5 w-3 rounded-sm bg-pink-500/30" />fast recovery</span></>}
                  <span className="flex items-center gap-1" style={{ color: STATUS.fast_retransmit }}>▼ fast retx</span>
                  <span className="flex items-center gap-1" style={{ color: STATUS.timeout }}>◆ timeout</span>
                  <span className="flex items-center gap-1" style={{ color: STATUS.drop }}>✕ drop</span>
                  <label className="flex items-center gap-1.5"><input type="checkbox" checked={clip} onChange={(e) => setClip(e.target.checked)} />clip inflation</label>
                </div>}>
              <CwndChart sim={sim} clip={clip} onEvent={setSel} />
              {clip && sim.cwnd.some((c) => c.inflation_cap) && (
                <p className="mt-2 text-xs text-fg-3">Fast-recovery window inflation (RFC 5681/6582: +1 segment per duplicate ACK) peaks at {fmt(k.peak_cwnd, 0)} segments; the axis is clipped. Untick to see it.</p>
              )}
            </Card>
            <div className="grid gap-5 xl:grid-cols-2">
              <Card title="Bottleneck queue occupancy" subtitle="Packets waiting; dashed line = buffer limit"><QueueChart sim={sim} /></Card>
              <Card title="Round-trip time" subtitle="Per ACK (Karn); above the base RTT is queueing delay"><RttChart sim={sim} /></Card>
            </div>

            <Card title="Event feed" subtitle={`${sim.events_total} congestion events · rule-based explanations generated from the event log`}
              right={
                <select className="rounded-md border border-ink-600 bg-ink-900 px-2 py-1 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)}>
                  <option value="all">All events</option>
                  {kinds.map((k) => <option key={k} value={k}>{EVENT_LABEL[k] ?? k}</option>)}
                </select>} pad={false}>
              <div className="max-h-80 divide-y divide-ink-600/60 overflow-y-auto">
                {feed.length === 0 && <div className="p-4 text-sm text-fg-3">No events of this type.</div>}
                {feed.slice(0, 250).map((e, i) => (
                  <button key={i} onClick={() => setSel(e)} className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm hover:bg-ink-700/40">
                    <span className="tnum w-20 shrink-0 font-mono text-xs text-fg-3">{e.t.toFixed(4)}s</span>
                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: STATUS[e.event] ?? C.fg3 }} />
                    <span className="w-44 shrink-0 font-medium">{EVENT_LABEL[e.event] ?? e.event}</span>
                    <span className="shrink-0 text-xs" style={{ color: flowColor(e.flow) }}>flow {e.flow}</span>
                    <span className="truncate text-xs text-fg-3">{e.info}</span>
                  </button>
                ))}
              </div>
            </Card>
          </>
        )}
      </div>

      <Modal open={!!sel} onClose={() => setSel(null)} title={sel ? <span className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full" style={{ background: STATUS[sel.event] }} />{EVENT_LABEL[sel.event] ?? sel.event}
        <span className="font-mono text-xs text-fg-3">t = {sel.t.toFixed(4)} s · flow {sel.flow}{sel.seq >= 0 ? ` · seg ${sel.seq}` : ""}</span></span> : ""}>
        {sel && (
          <div className="space-y-4 text-sm">
            {sel.rule && (
              <div className="flex items-start gap-2 rounded-lg border border-blue/30 bg-blue/10 p-3 text-blue">
                <BookOpen size={15} className="mt-0.5 shrink-0" /><span className="font-medium">{sel.rule}</span>
              </div>
            )}
            <p className="leading-relaxed text-fg-2">{sel.explanation}</p>
            <div className="grid grid-cols-3 gap-2 text-xs">
              {[["cwnd after", fmt(sel.cwnd, 2)], ["ssthresh", fmt(sel.ssthresh, 2)], ["queue", `${sel.queue}`]].map(([l, v]) => (
                <div key={l} className="rounded-lg border border-ink-600 bg-ink-900 p-2"><div className="text-fg-3">{l}</div><div className="tnum font-mono text-fg">{v}</div></div>
              ))}
            </div>
            <div className="font-mono text-[11px] text-fg-3">raw log: {sel.info}</div>
            <Badge tone="muted">{ALGO_LABEL[sim?.flows[sel.flow]?.algorithm ?? ""] ?? "cross traffic"}</Badge>
            <span className={clsx("ml-2 text-xs")} style={{ color: ALGO_COLOR[sim?.flows[sel.flow]?.algorithm ?? ""] }} />
          </div>
        )}
      </Modal>
    </div>
  );
}
