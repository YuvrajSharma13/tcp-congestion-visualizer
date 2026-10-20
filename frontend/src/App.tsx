import { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { motion } from "framer-motion";
import { Activity, Boxes, Cpu, FlaskConical, GitCompareArrows, Play, ShieldCheck, Sparkles } from "lucide-react";
import { api, DEFAULT_PARAMS, type SimParams, type SimResult } from "./lib/api";
import SimulationLab from "./pages/SimulationLab";
import PacketCanvasPage from "./pages/PacketCanvasPage";
import Comparison from "./pages/Comparison";
import Scenarios from "./pages/Scenarios";
import Predictor from "./pages/Predictor";
import Validation from "./pages/Validation";

const TABS = [
  { id: "lab", label: "Simulation Lab", icon: FlaskConical },
  { id: "canvas", label: "Packet Canvas", icon: Boxes, tag: "60 FPS" },
  { id: "compare", label: "Algorithm Comparison", icon: GitCompareArrows },
  { id: "scenarios", label: "Scenario Lab", icon: Sparkles },
  { id: "ai", label: "AI Predictor", icon: Cpu },
  { id: "validation", label: "Validation & RFCs", icon: ShieldCheck },
] as const;
type Tab = (typeof TABS)[number]["id"];

export interface SimState {
  params: SimParams;
  setParams: (p: SimParams | ((p: SimParams) => SimParams)) => void;
  sim: SimResult | null;
  prev: SimResult | null;
  loading: boolean;
  error: unknown;
  run: (override?: Partial<SimParams>) => Promise<SimResult | null>;
}

export default function App() {
  const initialTab = (window.location.hash.replace("#", "") as Tab) || "lab";
  const [tab, setTab] = useState<Tab>(TABS.some((t) => t.id === initialTab) ? initialTab : "lab");
  const [params, setParams] = useState<SimParams>(DEFAULT_PARAMS);
  const [sim, setSim] = useState<SimResult | null>(null);
  const [prev, setPrev] = useState<SimResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const reqId = useRef(0);

  useEffect(() => { window.location.hash = tab; }, [tab]);
  useEffect(() => {
    const ping = () => api.health().then(() => setOnline(true)).catch(() => setOnline(false));
    ping();
    const id = setInterval(ping, 15000);
    return () => clearInterval(id);
  }, []);

  const run = useCallback(async (override?: Partial<SimParams>) => {
    const p = { ...params, ...override };
    const id = ++reqId.current;
    setLoading(true); setError(null);
    try {
      const r = await api.simulate(p);
      if (id === reqId.current) { setPrev(sim); setSim(r); }
      return r;
    } catch (e) {
      if (id === reqId.current) setError(e);
      return null;
    } finally {
      if (id === reqId.current) setLoading(false);
    }
  }, [params, sim]);

  const state: SimState = { params, setParams, sim, prev, loading, error, run };

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-40 border-b border-ink-600/80 bg-ink-950/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1500px] items-center gap-4 px-5 py-3">
          <div className="flex items-center gap-3">
            <div className="grid h-8 w-8 place-items-center rounded-lg border border-ink-600 bg-ink-850">
              <Activity size={17} className="text-blue" />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-semibold tracking-tight">TCP Congestion Control Visualizer</div>
              <div className="text-[11px] text-fg-3">Tahoe · Reno · NewReno · CUBIC — discrete-event simulator</div>
            </div>
          </div>
          <span className={clsx("ml-2 hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium sm:inline-flex",
            online ? "border-emerald/40 bg-emerald/10 text-emerald" : online === false ? "border-ruby/40 bg-ruby/10 text-ruby" : "border-ink-600 text-fg-3")}>
            <span className="relative flex h-2 w-2">
              {online && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald opacity-60" />}
              <span className={clsx("relative inline-flex h-2 w-2 rounded-full", online ? "bg-emerald" : online === false ? "bg-ruby" : "bg-fg-3")} />
            </span>
            {online ? "Engine online" : online === false ? "API offline" : "Connecting"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <label className="hidden items-center gap-2 rounded-lg border border-ink-600 bg-ink-900 px-2.5 py-1.5 text-xs text-fg-3 md:flex" title="Random seed: identical seed + config ⇒ identical trace">
              seed
              <input type="number" value={params.seed} min={0} onChange={(e) => setParams({ ...params, seed: Math.max(0, parseInt(e.target.value || "0")) })}
                className="tnum w-16 bg-transparent font-mono text-fg outline-none" />
            </label>
            <button className="btn-primary" onClick={() => { run(); if (tab !== "lab" && tab !== "canvas") setTab("lab"); }} disabled={loading}>
              <Play size={15} /> {loading ? "Running…" : "Quick Run"}
            </button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-[1500px] gap-1 overflow-x-auto px-3">
          {TABS.map((t) => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={clsx("relative flex shrink-0 items-center gap-2 px-3 py-2.5 text-sm transition",
                tab === t.id ? "text-fg" : "text-fg-3 hover:text-fg-2")}>
              <t.icon size={15} />{t.label}
              {"tag" in t && <span className="rounded bg-blue/15 px-1.5 py-px font-mono text-[10px] text-blue">{t.tag}</span>}
              {tab === t.id && <motion.span layoutId="tab" className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-blue" />}
            </button>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-[1500px] px-5 py-6">
        {tab === "lab" && <SimulationLab s={state} />}
        {tab === "canvas" && <PacketCanvasPage s={state} />}
        {tab === "compare" && <Comparison s={state} />}
        {tab === "scenarios" && <Scenarios s={state} goLab={() => setTab("lab")} />}
        {tab === "ai" && <Predictor s={state} />}
        {tab === "validation" && <Validation />}
      </main>
      <footer className="mx-auto max-w-[1500px] px-5 pb-8 text-xs text-fg-3">
        Segment-level model (no SACK, delayed ACKs or pacing). Every chart is computed from the simulator's own event trace · RFC 5681 · 6582 · 6298 · 9438
      </footer>
    </div>
  );
}
