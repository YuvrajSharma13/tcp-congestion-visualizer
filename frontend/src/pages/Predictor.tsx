import { useState } from "react";
import { BrainCircuit, Info, Play } from "lucide-react";
import type { SimState } from "../App";
import { api, type PredictResult } from "../lib/api";
import { fmt } from "../lib/format";
import { C } from "../lib/theme";
import { RiskTimeline } from "../components/charts";
import { Card, Empty, ErrorBox, Spinner } from "../components/ui";

function Gauge({ p, risk }: { p: number; risk: string }) {
  const color = risk === "high" ? C.ruby : risk === "medium" ? C.amber : C.emerald;
  const a = Math.PI * (1 - p);
  const R = 80, cx = 100, cy = 96;
  const x = cx + R * Math.cos(a), y = cy - R * Math.sin(a);
  return (
    <svg viewBox="0 0 200 120" className="w-full max-w-[260px]">
      <defs><linearGradient id="gg"><stop offset="0%" stopColor={C.emerald} /><stop offset="55%" stopColor={C.amber} /><stop offset="100%" stopColor={C.ruby} /></linearGradient></defs>
      <path d={`M${cx - R},${cy} A${R},${R} 0 0 1 ${cx + R},${cy}`} stroke="#232a38" strokeWidth="14" fill="none" strokeLinecap="round" />
      <path d={`M${cx - R},${cy} A${R},${R} 0 0 1 ${x},${y}`} stroke="url(#gg)" strokeWidth="14" fill="none" strokeLinecap="round" />
      <circle cx={x} cy={y} r="7" fill={color} stroke="#0b0e14" strokeWidth="3" />
      <text x={cx} y={cy - 14} textAnchor="middle" fill={C.fg} fontSize="26" fontWeight="600">{Math.round(p * 100)}%</text>
      <text x={cx} y={cy + 6} textAnchor="middle" fill={color} fontSize="12" fontWeight="700" letterSpacing="2">{risk.toUpperCase()} RISK</text>
    </svg>
  );
}

export default function Predictor({ s }: { s: SimState }) {
  const [r, setR] = useState<PredictResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const go = async () => { setBusy(true); setErr(null); try { setR(await api.predict(s.params)); } catch (e) { setErr(e); } finally { setBusy(false); } };
  const ch = r?.model ?? "";
  const ev = r?.evaluation ?? {};
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">AI congestion predictor</h1>
          <p className="mt-1 max-w-3xl text-sm text-fg-2">A random-forest classifier reads the run's recorded telemetry (queue, RTT, loss, cwnd, utilisation over the last 200 ms) and estimates the probability that the bottleneck buffer overflows in the next 200 ms.</p>
        </div>
        <button className="btn-primary" onClick={go} disabled={busy}>{busy ? <Spinner label="Simulating + predicting…" /> : <><Play size={15} />Predict on current configuration</>}</button>
      </div>
      <div className="flex items-start gap-2 rounded-xl border border-amber/30 bg-amber/5 p-3 text-sm text-fg-2">
        <Info size={16} className="mt-0.5 shrink-0 text-amber" />
        Research and learning feature, not a TCP controller: predictions are computed after the run and never change cwnd or any algorithm state.
      </div>
      <ErrorBox error={err} />
      {!r && <Empty icon={<BrainCircuit size={22} />} title="No prediction yet">Uses the Simulation Lab configuration ({s.params.bandwidth_mbps} Mbps, buffer {s.params.buffer_packets}, {s.params.n_flows} flow(s)).</Empty>}
      {r && !r.available && <Empty icon={<BrainCircuit size={22} />} title="Model unavailable">{r.message} Train it with <code>python -m ml.train</code>.</Empty>}
      {r && r.available && r.peak && (
        <>
          <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
            <Card title="Peak predicted risk" subtitle={`at t = ${fmt(r.peak.t, 2)} s`}>
              <div className="flex flex-col items-center"><Gauge p={r.peak.prob} risk={r.peak.risk} /></div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg border border-ink-600 bg-ink-900 p-2"><div className="text-fg-3">mean risk</div><div className="tnum font-mono">{fmt(r.peak.mean_prob * 100, 1)}%</div></div>
                <div className="rounded-lg border border-ink-600 bg-ink-900 p-2"><div className="text-fg-3">time at high risk</div><div className="tnum font-mono">{fmt(r.peak.high_fraction * 100, 1)}%</div></div>
              </div>
            </Card>
            <Card title="Risk timeline" subtitle={`Horizon ${(r.horizon_s ?? 0) * 1000} ms · red ticks = an overflow really followed`}>
              <RiskTimeline points={r.points} threshold={r.threshold ?? 0.5} horizon={r.horizon_s ?? 0.2} />
              {r.run_metrics && <p className="mt-2 text-xs text-fg-3">On this run: precision {fmt(r.run_metrics.precision)}, recall {fmt(r.run_metrics.recall)}, ROC-AUC {fmt(r.run_metrics.roc_auc)} (illustrative — the honest evaluation is on held-out networks, right).</p>}
            </Card>
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Why the peak was high" subtitle="Logistic-regression contributions at the peak">
              <p className="mb-3 text-sm text-fg-2">{r.explanation}</p>
              {r.contributions.map((c) => (
                <div key={c.feature} className="mb-2">
                  <div className="flex justify-between text-xs"><span className="text-fg-2">{c.label}</span><span className="tnum font-mono text-fg-3">value {fmt(c.value, 3)}</span></div>
                  <div className="mt-1 flex h-2 overflow-hidden rounded bg-ink-900">
                    <div className="h-full rounded" style={{ width: `${Math.min(Math.abs(c.contribution) * 20, 100)}%`, background: c.contribution > 0 ? C.ruby : C.emerald }} />
                  </div>
                </div>
              ))}
            </Card>
            <Card title="Held-out evaluation" subtitle="Test set = network configurations never seen in training">
              <table className="w-full text-xs">
                <thead className="text-left text-fg-3"><tr><th className="py-1">model</th><th>precision</th><th>recall</th><th>F1</th><th>ROC-AUC</th><th>Brier</th></tr></thead>
                <tbody className="tnum font-mono">
                  {Object.entries(ev).map(([k, m]) => (
                    <tr key={k} className={k === ch ? "text-fg" : "text-fg-2"}>
                      <td className="py-1 font-sans">{k.replace(/_/g, " ")}{k === ch ? " ★" : ""}</td>
                      <td>{fmt(m.precision, 3)}</td><td>{fmt(m.recall, 3)}</td><td>{fmt(m.f1, 3)}</td><td>{fmt(m.roc_auc, 3)}</td><td>{fmt(m.brier, 3)}</td>
                    </tr>))}
                </tbody>
              </table>
              <div className="mt-4 label">Permutation importance</div>
              {Object.entries(r.importance).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([k, v]) => (
                <div key={k} className="mt-1.5 flex items-center gap-2 text-xs">
                  <span className="w-36 truncate text-fg-2">{k.replace(/_/g, " ")}</span>
                  <div className="h-1.5 flex-1 rounded bg-ink-900"><div className="h-full rounded bg-blue" style={{ width: `${Math.max(v, 0) / Math.max(...Object.values(r.importance)) * 100}%` }} /></div>
                  <span className="tnum w-12 text-right font-mono text-fg-3">{v.toFixed(3)}</span>
                </div>))}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
