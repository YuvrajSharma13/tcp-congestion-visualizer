import { useEffect, useState } from "react";
import clsx from "clsx";
import { motion } from "framer-motion";
import { CheckCircle2, Circle, Eye, FlaskConical, Play, Sparkles, XCircle } from "lucide-react";
import type { SimState } from "../App";
import { ALGO_LABEL, ALGORITHMS, api, type Algorithm, type ScenarioInfo, type ScenarioResult } from "../lib/api";
import { fmt } from "../lib/format";
import { OverlayCwnd } from "../components/charts";
import { AlgoDot, Badge, Card, ErrorBox, Spinner } from "../components/ui";

export default function Scenarios({ s, goLab }: { s: SimState; goLab: () => void }) {
  const [list, setList] = useState<ScenarioInfo[]>([]);
  const [alg, setAlg] = useState<Algorithm>("reno");
  const [busy, setBusy] = useState<string | null>(null);
  const [res, setRes] = useState<Record<string, ScenarioResult>>({});
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { api.scenarios().then(setList).catch(setErr); }, []);

  const runOne = async (id: string) => {
    setBusy(id); setErr(null); setOpen(id);
    try { const r = await api.runScenario(id, alg); setRes((m) => ({ ...m, [id]: r })); } catch (e) { setErr(e); } finally { setBusy(null); }
  };
  const runCustom = async () => { setBusy("custom"); await s.run(); setBusy(null); goLab(); };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Scenario Lab</h1>
          <p className="mt-1 text-sm text-fg-2">Ten classic experiments. After each run the measured results are checked against networking theory — no algorithm is assumed to win.</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-fg-3">Algorithm for single-algorithm scenarios
          <div className="flex gap-1 rounded-lg border border-ink-600 bg-ink-900 p-1">
            {ALGORITHMS.map((a) => <button key={a} onClick={() => setAlg(a)} className={clsx("flex items-center gap-1.5 rounded-md px-2 py-1",
              a === alg ? "bg-ink-700 text-fg" : "hover:text-fg-2")}><AlgoDot algorithm={a} />{ALGO_LABEL[a]}</button>)}
          </div>
        </div>
      </div>
      <ErrorBox error={err} />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {list.map((sc, i) => {
          const r = res[sc.id];
          const ok = r?.checks.filter((c) => c.status === "consistent").length ?? 0;
          const bad = r?.checks.filter((c) => c.status === "not observed").length ?? 0;
          return (
            <motion.div key={sc.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}
              className={clsx("card flex flex-col p-4 transition hover:border-ink-500", open === sc.id && "border-blue/50 shadow-glow")}>
              <div className="flex items-start justify-between gap-2">
                <div className="font-mono text-[11px] text-fg-3">#{String(i + 1).padStart(2, "0")}</div>
                {r ? <div className="flex gap-1">{ok > 0 && <Badge tone="good">{ok} ✓</Badge>}{bad > 0 && <Badge tone="bad">{bad} ✗</Badge>}</div>
                  : sc.fixed_algorithms ? <Badge tone="muted">fixed algorithms</Badge> : <Badge tone="info">{ALGO_LABEL[alg]}</Badge>}
              </div>
              <h3 className="mt-1 font-semibold">{sc.title}</h3>
              <p className="mt-1 flex-1 text-sm text-fg-2">{sc.summary}</p>
              <div className="mt-2 text-xs text-fg-3">{sc.runs.length} run{sc.runs.length > 1 ? "s" : ""}: {sc.runs.join(" · ")}</div>
              <div className="mt-3 flex gap-2">
                <button className="btn-primary flex-1" disabled={!!busy} onClick={() => runOne(sc.id)}>
                  {busy === sc.id ? <Spinner label="Running…" /> : <><Play size={14} />Run experiment</>}
                </button>
                {r && <button className="btn-ghost" onClick={() => setOpen(open === sc.id ? null : sc.id)}><Eye size={14} /></button>}
              </div>
            </motion.div>
          );
        })}
        <div className="card flex flex-col border-dashed p-4">
          <div className="font-mono text-[11px] text-fg-3">#10</div>
          <h3 className="mt-1 font-semibold">Custom scenario</h3>
          <p className="mt-1 flex-1 text-sm text-fg-2">Run whatever is configured in the Simulation Lab ({s.params.bandwidth_mbps} Mbps, {s.params.delay_ms} ms, buffer {s.params.buffer_packets}, loss {s.params.loss_rate}%).</p>
          <button className="btn-ghost mt-3" disabled={!!busy} onClick={runCustom}>{busy === "custom" ? <Spinner /> : <><FlaskConical size={14} />Open in Simulation Lab</>}</button>
        </div>
      </div>

      {open && res[open] && <ScenarioDetail r={res[open]} info={list.find((x) => x.id === open)!} />}
    </div>
  );
}

function ScenarioDetail({ r, info }: { r: ScenarioResult; info: ScenarioInfo }) {
  return (
    <Card title={<span className="flex items-center gap-2"><Sparkles size={15} className="text-blue" />{r.title}: expected vs. observed</span>}
      subtitle={info.observe.join(" ")}>
      <div className="grid gap-3 lg:grid-cols-2">
        {r.checks.map((c, i) => {
          const tone = c.status === "consistent" ? "good" : c.status === "not observed" ? "bad" : "info";
          const Icon = c.status === "consistent" ? CheckCircle2 : c.status === "not observed" ? XCircle : Circle;
          return (
            <motion.div key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }}
              className={clsx("rounded-xl border p-3", tone === "good" ? "border-emerald/30 bg-emerald/5" : tone === "bad" ? "border-ruby/30 bg-ruby/5" : "border-blue/25 bg-blue/5")}>
              <div className="flex items-center gap-2">
                <Icon size={16} className={tone === "good" ? "text-emerald" : tone === "bad" ? "text-ruby" : "text-blue"} />
                <Badge tone={tone}>{c.status === "consistent" ? "Consistent with theory" : c.status === "not observed" ? "Not observed" : "Observation"}</Badge>
              </div>
              <div className="mt-2 text-sm font-medium text-fg">{c.expectation}</div>
              <div className="mt-1 font-mono text-xs text-fg-2">{c.observed}</div>
            </motion.div>
          );
        })}
      </div>
      <div className="mt-5 grid gap-4 xl:grid-cols-2">
        {r.runs.map((run) => (
          <div key={run.label} className="rounded-xl border border-ink-600 bg-ink-900/60 p-3">
            <div className="mb-1 flex items-center justify-between text-sm"><span className="font-medium">{run.label}</span>
              <span className="tnum font-mono text-xs text-fg-3">{fmt(run.kpis.goodput_mbps)} Mbps · loss {fmt(run.kpis.loss_pct)}% · {run.kpis.timeouts} RTO</span></div>
            <OverlayCwnd series={run.cwnd} clip height={200} />
          </div>
        ))}
      </div>
    </Card>
  );
}
