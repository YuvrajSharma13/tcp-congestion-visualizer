import { useState } from "react";
import clsx from "clsx";
import { motion } from "framer-motion";
import { Flag, GitCompareArrows, Lightbulb } from "lucide-react";
import type { SimState } from "../App";
import { ALGO_LABEL, ALGORITHMS, api, type Algorithm, type CompareResult } from "../lib/api";
import { fmt } from "../lib/format";
import { ALGO_COLOR } from "../lib/theme";
import { MetricBars, OverlayCwnd } from "../components/charts";
import { AlgoDot, Card, Empty, ErrorBox, Spinner } from "../components/ui";

const PRESETS: { name: string; p: Record<string, number> }[] = [
  { name: "High BDP · 50 Mbps / 60 ms / 0.01% loss", p: { bandwidth_mbps: 50, delay_ms: 60, buffer_packets: 250, loss_rate: 0.01, duration_s: 40, initial_ssthresh: 300 } },
  { name: "Baseline · 10 Mbps / 20 ms", p: { bandwidth_mbps: 10, delay_ms: 20, buffer_packets: 35, loss_rate: 0, duration_s: 20, initial_ssthresh: 64 } },
  { name: "Lossy · 1% random loss", p: { bandwidth_mbps: 10, delay_ms: 20, buffer_packets: 35, loss_rate: 1, duration_s: 30, initial_ssthresh: 64 } },
  { name: "Shallow buffer · 4 pkts", p: { bandwidth_mbps: 10, delay_ms: 20, buffer_packets: 4, loss_rate: 0, duration_s: 30, initial_ssthresh: 64 } },
];

export default function Comparison({ s }: { s: SimState }) {
  const [algs, setAlgs] = useState<Algorithm[]>([...ALGORITHMS]);
  const [res, setRes] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [clip, setClip] = useState(true);
  const p = s.params;

  const go = async (override?: Record<string, number>) => {
    const params = { ...p, ...override, algorithms: null };
    if (override) s.setParams(params);
    setLoading(true); setErr(null);
    try { setRes(await api.compare(params, algs)); } catch (e) { setErr(e); } finally { setLoading(false); }
  };
  const best = res ? Math.max(...res.rows.map((r) => r.goodput_mbps)) : 1;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Algorithm Comparison Arena</h1>
        <p className="mt-1 text-sm text-fg-2">Same bandwidth, delay, buffer, loss probability, flow count and random seed — only the congestion-control algorithm changes.</p>
      </div>
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex gap-1 rounded-lg border border-ink-600 bg-ink-900 p-1">
            {ALGORITHMS.map((a) => (
              <button key={a} onClick={() => setAlgs(algs.includes(a) ? algs.filter((x) => x !== a) : [...algs, a])}
                className={clsx("flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium",
                  algs.includes(a) ? "bg-ink-700 text-fg" : "text-fg-3 line-through")}>
                <AlgoDot algorithm={a} />{ALGO_LABEL[a]}
              </button>
            ))}
          </div>
          <div className="text-xs text-fg-3">
            Network: {p.bandwidth_mbps} Mbps · {p.delay_ms} ms · buffer {p.buffer_packets} · loss {p.loss_rate}% · {p.duration_s} s · {p.n_flows} flow(s) · seed {p.seed}
          </div>
          <button className="btn-primary ml-auto" disabled={loading || !algs.length} onClick={() => go()}>
            {loading ? <Spinner label="Racing…" /> : <><Flag size={15} />Start race</>}
          </button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {PRESETS.map((x) => (
            <button key={x.name} className="rounded-full border border-ink-600 px-3 py-1 text-xs text-fg-2 hover:border-blue/50 hover:text-fg"
              onClick={() => go(x.p)} disabled={loading}>{x.name}</button>
          ))}
        </div>
      </Card>
      <ErrorBox error={err} />
      {!res && !loading && <Empty icon={<GitCompareArrows size={22} />} title="Pick algorithms and start the race">
        Try the <b>High BDP</b> preset: Reno climbs one segment per RTT while CUBIC's window follows a cubic curve of time.</Empty>}
      {res && (
        <>
          <Card title="Drag race · goodput delivered" subtitle="Bar length ∝ average goodput over the run">
            <div className="space-y-3">
              {[...res.rows].sort((a, b) => b.goodput_mbps - a.goodput_mbps).map((r, i) => (
                <div key={r.algorithm} className="flex items-center gap-3">
                  <div className="flex w-24 items-center gap-2 text-sm"><AlgoDot algorithm={r.algorithm} />{ALGO_LABEL[r.algorithm]}</div>
                  <div className="relative h-7 flex-1 overflow-hidden rounded-md bg-ink-900">
                    <motion.div className="absolute inset-y-0 left-0 rounded-md" style={{ background: `linear-gradient(90deg, ${ALGO_COLOR[r.algorithm]}55, ${ALGO_COLOR[r.algorithm]})` }}
                      initial={{ width: 0 }} animate={{ width: `${(r.goodput_mbps / best) * 100}%` }} transition={{ duration: 1.2 + i * 0.25, ease: "easeOut" }} />
                  </div>
                  <div className="tnum w-28 text-right font-mono text-sm">{fmt(r.goodput_mbps, 2)} Mbps</div>
                </div>
              ))}
            </div>
          </Card>
          <Card title="Congestion window, overlaid (flow 0)" right={<label className="flex items-center gap-1.5 text-xs text-fg-3"><input type="checkbox" checked={clip} onChange={(e) => setClip(e.target.checked)} />clip fast-recovery inflation</label>}>
            <OverlayCwnd series={res.cwnd} clip={clip} />
          </Card>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {([["goodput_mbps", "Goodput", "Mbps", 2], ["avg_rtt_ms", "Average RTT", "ms", 1], ["loss_pct", "Packet loss", "%", 2],
              ["link_util_pct", "Link utilisation", "%", 1], ["timeouts", "Timeouts", "", 0], ["median_regain_s", "Median recovery time", "s", 2]] as const).map(([m, t, u, d]) => (
              <Card key={m} title={t} subtitle={u ? `unit: ${u}` : undefined}><MetricBars rows={res.rows} metric={m} unit={u} digits={d} /></Card>
            ))}
          </div>
          <Card title="What the data shows" right={<Lightbulb size={16} className="text-amber" />}>
            <ul className="space-y-2 text-sm text-fg-2">{res.notes.map((n) => <li key={n} className="flex gap-2"><span className="text-blue">›</span>{n}</li>)}</ul>
          </Card>
          <Card title="Full table" pad={false}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-fg-3"><tr className="border-b border-ink-600">
                  {["Algorithm", "Goodput", "Util %", "Loss %", "Avg RTT", "Avg queue", "Fast retx", "Timeouts", "Retx pkts", "Recovery s", "Startup s", "Jain"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}
                </tr></thead>
                <tbody className="tnum font-mono text-xs">
                  {res.rows.map((r) => (
                    <tr key={r.algorithm} className="border-b border-ink-600/50">
                      <td className="px-4 py-2 font-sans text-sm"><span className="flex items-center gap-2"><AlgoDot algorithm={r.algorithm} />{ALGO_LABEL[r.algorithm]}</span></td>
                      <td className="px-4">{fmt(r.goodput_mbps)}</td><td className="px-4">{fmt(r.link_util_pct, 1)}</td><td className="px-4">{fmt(r.loss_pct)}</td>
                      <td className="px-4">{fmt(r.avg_rtt_ms, 1)}</td><td className="px-4">{fmt(r.avg_queue_pkts, 1)}</td><td className="px-4">{r.fast_retransmits}</td>
                      <td className="px-4">{r.timeouts}</td><td className="px-4">{r.retx_packets}</td><td className="px-4">{fmt(r.median_regain_s)}</td>
                      <td className="px-4">{fmt(r.startup_s)}</td><td className="px-4">{fmt(r.jain_index, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
