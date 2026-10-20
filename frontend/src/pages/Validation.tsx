import { useEffect, useState } from "react";
import clsx from "clsx";
import { CheckCircle2, MinusCircle, ShieldCheck, XCircle } from "lucide-react";
import { api, type ValidationResult } from "../lib/api";
import { Card, ErrorBox, Spinner } from "../components/ui";

export default function Validation() {
  const [v, setV] = useState<ValidationResult | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [scope, setScope] = useState("all");
  useEffect(() => { api.validation().then(setV).catch(setErr); }, []);
  if (err) return <ErrorBox error={err} />;
  if (!v) return <div className="card grid h-64 place-items-center"><Spinner label="Running RFC rule probes and trace audits…" /></div>;
  const items = v.items.filter((i) => scope === "all" || i.scope === scope);
  const total = v.passed + v.failed;
  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-[1.2fr_1fr_1fr_1fr]">
        <div className="card relative overflow-hidden p-5">
          <div className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-emerald/20 blur-3xl" />
          <ShieldCheck className={v.failed ? "text-ruby" : "text-emerald"} size={28} />
          <div className="mt-2 text-2xl font-semibold">{v.failed ? `${v.failed} checks failing` : "All checks pass"}</div>
          <div className="text-sm text-fg-2">{v.passed}/{total} rules verified · audited run: {v.audited_run}</div>
        </div>
        {[["Passed", v.passed, "text-emerald"], ["Failed", v.failed, "text-ruby"], ["Not applicable", v.not_applicable, "text-fg-3"]].map(([l, n, c]) => (
          <div key={l as string} className="card p-5"><div className="label">{l}</div><div className={clsx("tnum mt-2 text-3xl font-semibold", c as string)}>{n}</div></div>
        ))}
      </div>
      <div className="flex gap-1">
        {["all", "rule probe", "trace audit"].map((s) => (
          <button key={s} onClick={() => setScope(s)} className={clsx("rounded-md px-3 py-1.5 text-xs", scope === s ? "bg-ink-700 text-fg" : "text-fg-3 hover:text-fg-2")}>{s}</button>
        ))}
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {items.map((i, k) => {
          const Icon = i.status === "pass" ? CheckCircle2 : i.status === "fail" ? XCircle : MinusCircle;
          return (
            <div key={k} className={clsx("card p-4", i.status === "fail" && "border-ruby/40")}>
              <div className="flex items-start gap-2">
                <Icon size={17} className={clsx("mt-0.5 shrink-0", i.status === "pass" ? "text-emerald" : i.status === "fail" ? "text-ruby" : "text-fg-3")} />
                <div>
                  <div className="text-sm font-medium leading-snug">{i.check}</div>
                  <div className="mt-1 inline-block rounded border border-blue/30 bg-blue/10 px-1.5 py-px font-mono text-[10px] text-blue">{i.reference}</div>
                  <div className="mt-1.5 text-xs text-fg-3">{i.detail}</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <Card title="Modelling assumptions that limit comparison with a real TCP stack">
        <div className="grid gap-x-6 gap-y-3 md:grid-cols-2">
          {v.limitations.map(([a, b]) => <div key={a}><div className="text-sm font-medium">{a}</div><div className="text-xs text-fg-3">{b}</div></div>)}
        </div>
      </Card>
    </div>
  );
}
