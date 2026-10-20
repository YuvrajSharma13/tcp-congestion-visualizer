import clsx from "clsx";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, Loader2, X, ArrowUpRight, ArrowDownRight, Minus } from "lucide-react";
import type { ReactNode } from "react";
import { ALGO_LABEL, ApiError, type Algorithm } from "../lib/api";
import { ALGO_COLOR } from "../lib/theme";

export function Card({ title, subtitle, right, children, className, pad = true }: {
  title?: ReactNode; subtitle?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean;
}) {
  return (
    <section className={clsx("card", className)}>
      {(title || right) && (
        <header className="flex items-start justify-between gap-3 border-b border-ink-600/70 px-4 py-3">
          <div>
            {title && <h3 className="text-sm font-semibold text-fg">{title}</h3>}
            {subtitle && <p className="mt-0.5 text-xs text-fg-3">{subtitle}</p>}
          </div>
          {right}
        </header>
      )}
      <div className={clsx(pad && "p-4")}>{children}</div>
    </section>
  );
}

export function Kpi({ label, value, hint, accent = "#3b82f6", delta }: {
  label: string; value: string; hint?: string; accent?: string; delta?: number | null;
}) {
  return (
    <motion.div layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
      className="card relative overflow-hidden p-4">
      <div className="pointer-events-none absolute -right-8 -top-10 h-28 w-28 rounded-full blur-2xl"
        style={{ background: accent, opacity: 0.16 }} />
      <div className="label">{label}</div>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span className="tnum text-2xl font-semibold tracking-tight text-fg">{value}</span>
        {delta !== undefined && delta !== null && Number.isFinite(delta) && <Delta v={delta} />}
      </div>
      {hint && <div className="mt-1 text-xs text-fg-3">{hint}</div>}
      <div className="absolute inset-x-0 bottom-0 h-px" style={{ background: `linear-gradient(90deg, ${accent}, transparent)` }} />
    </motion.div>
  );
}

function Delta({ v }: { v: number }) {
  const flat = Math.abs(v) < 0.5;
  const Icon = flat ? Minus : v > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span title="change vs previous run" className={clsx("tnum inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] font-medium",
      flat ? "bg-ink-700 text-fg-3" : v > 0 ? "bg-emerald/10 text-emerald" : "bg-ruby/10 text-ruby")}>
      <Icon size={12} />{Math.abs(v).toFixed(1)}%
    </span>
  );
}

export function AlgoDot({ algorithm, className }: { algorithm: string; className?: string }) {
  return <span className={clsx("inline-block h-2.5 w-2.5 rounded-[3px]", className)} style={{ background: ALGO_COLOR[algorithm] }} />;
}

export function AlgoPicker({ value, onChange }: { value: Algorithm; onChange: (a: Algorithm) => void }) {
  return (
    <div className="grid grid-cols-4 gap-1 rounded-lg border border-ink-600 bg-ink-900 p-1">
      {(["tahoe", "reno", "newreno", "cubic"] as Algorithm[]).map((a) => (
        <button key={a} onClick={() => onChange(a)}
          className={clsx("flex items-center justify-center gap-1.5 rounded-md px-1 py-1.5 text-xs font-medium transition",
            value === a ? "bg-ink-700 text-fg shadow-[inset_0_0_0_1px_#2f3849]" : "text-fg-3 hover:text-fg-2")}>
          <AlgoDot algorithm={a} />{ALGO_LABEL[a]}
        </button>
      ))}
    </div>
  );
}

export function Slider({ label, value, min, max, step, unit, onChange, format, help, log }: {
  label: string; value: number; min: number; max: number; step: number; unit?: string;
  onChange: (v: number) => void; format?: (v: number) => string; help?: string; log?: boolean;
}) {
  // optional log scale for wide ranges
  const toPos = (v: number) => (log ? Math.log(v) : v);
  const fromPos = (p: number) => (log ? Math.exp(p) : p);
  const shown = format ? format(value) : `${value}`;
  return (
    <label className="block" title={help}>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-xs font-medium text-fg-2">{label}</span>
        <span className="tnum rounded-md border border-ink-600 bg-ink-900 px-1.5 py-0.5 font-mono text-[11px] text-fg">
          {shown}{unit && <span className="text-fg-3"> {unit}</span>}
        </span>
      </div>
      <input type="range" className="slider" min={toPos(min)} max={toPos(max)} step={log ? 0.001 : step}
        value={toPos(value)} onChange={(e) => {
          let v = fromPos(parseFloat(e.target.value));
          v = Math.round(v / step) * step;
          onChange(Number(v.toFixed(6)));
        }} />
    </label>
  );
}

export function Spinner({ label }: { label?: string }) {
  return <span className="inline-flex items-center gap-2 text-sm text-fg-2"><Loader2 className="animate-spin" size={16} />{label}</span>;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error as ApiError;
  return (
    <div className="flex gap-3 rounded-xl border border-ruby/40 bg-ruby/10 p-3 text-sm text-fg">
      <AlertTriangle className="mt-0.5 shrink-0 text-ruby" size={16} />
      <div>
        <div className="font-medium">{e.message ?? String(error)}</div>
        {e.details?.length > 0 && <ul className="mt-1 list-disc pl-4 text-xs text-fg-2">{e.details.map((d) => <li key={d}>{d}</li>)}</ul>}
      </div>
    </div>
  );
}

export function Badge({ tone, children }: { tone: "good" | "warn" | "bad" | "info" | "muted"; children: ReactNode }) {
  const cls = {
    good: "border-emerald/40 bg-emerald/10 text-emerald", warn: "border-amber/40 bg-amber/10 text-amber",
    bad: "border-ruby/40 bg-ruby/10 text-ruby", info: "border-blue/40 bg-blue/10 text-blue",
    muted: "border-ink-500 bg-ink-700 text-fg-2",
  }[tone];
  return <span className={clsx("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold", cls)}>{children}</span>;
}

export function Modal({ open, onClose, children, title }: { open: boolean; onClose: () => void; children: ReactNode; title: ReactNode }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
          <motion.div className="card w-full max-w-xl shadow-2xl" initial={{ y: 16, scale: 0.98 }} animate={{ y: 0, scale: 1 }}
            exit={{ y: 10, opacity: 0 }} onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-ink-600 px-5 py-3">
              <div className="text-sm font-semibold">{title}</div>
              <button className="text-fg-3 hover:text-fg" onClick={onClose} aria-label="Close"><X size={18} /></button>
            </div>
            <div className="p-5">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <div className="rounded-xl border border-ink-600 bg-ink-900 p-3 text-blue">{icon}</div>
      <div className="text-base font-semibold">{title}</div>
      {children && <div className="max-w-md text-sm text-fg-2">{children}</div>}
    </div>
  );
}

export function Tooltip({ active, payload, label, unit, labelFmt }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-950/95 px-3 py-2 text-xs shadow-xl">
      <div className="mb-1 font-mono text-fg-3">{labelFmt ? labelFmt(label) : `t = ${Number(label).toFixed(3)} s`}</div>
      {payload.filter((p: any) => p.value !== null && p.value !== undefined).map((p: any) => (
        <div key={p.dataKey + p.name} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-sm" style={{ background: p.color || p.stroke }} />
          <span className="text-fg-2">{p.name}</span>
          <span className="tnum ml-auto pl-3 font-mono text-fg">{typeof p.value === "number" ? p.value.toFixed(2) : p.value}{unit ? ` ${unit}` : ""}</span>
        </div>
      ))}
    </div>
  );
}

export { ArrowUpRight };
