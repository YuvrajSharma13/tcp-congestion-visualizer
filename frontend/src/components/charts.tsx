import { useMemo } from "react";
import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Scatter,
  ComposedChart, Tooltip as RTooltip, XAxis, YAxis, Legend,
} from "recharts";
import { ALGO_LABEL, type CwndSeries, type EventItem, type SimResult } from "../lib/api";
import { ALGO_COLOR, C, STATUS, flowColor } from "../lib/theme";
import { Tooltip } from "./ui";

const axis = { stroke: C.border, tick: { fill: C.fg3, fontSize: 11 }, tickLine: false };

const MARK_EVENTS = ["fast_retransmit", "timeout", "partial_ack", "drop"];

function EventShape(props: any) {
  const { cx, cy, payload } = props;
  if (cx == null || cy == null) return null;
  const color = STATUS[payload.event] ?? C.fg;
  const s = 5;
  const common = { fill: color, stroke: C.bg, strokeWidth: 1.5, style: { cursor: "pointer" } };
  if (payload.event === "timeout") return <path d={`M${cx},${cy - s - 1} L${cx + s + 1},${cy} L${cx},${cy + s + 1} L${cx - s - 1},${cy} Z`} {...common} />;
  if (payload.event === "fast_retransmit") return <path d={`M${cx - s},${cy - s} L${cx + s},${cy - s} L${cx},${cy + s} Z`} {...common} />;
  if (payload.event === "drop") return <g style={{ cursor: "pointer" }}><circle cx={cx} cy={cy} r={8} fill="transparent" /><path d={`M${cx - 4},${cy - 4} L${cx + 4},${cy + 4} M${cx + 4},${cy - 4} L${cx - 4},${cy + 4}`} stroke={color} strokeWidth={2.2} /></g>;
  return <circle cx={cx} cy={cy} r={s} fill="transparent" stroke={color} strokeWidth={2} style={{ cursor: "pointer" }} />;
}

export function CwndChart({ sim, clip, onEvent, height = 320, showEvents = true }: {
  sim: SimResult; clip: boolean; onEvent?: (e: EventItem) => void; height?: number; showEvents?: boolean;
}) {
  const multi = sim.cwnd.length > 1;
  const cap = useMemo(() => {
    if (!clip) return undefined;
    const caps = sim.cwnd.map((s) => s.inflation_cap).filter((x): x is number => x !== null);
    if (!caps.length) return undefined;
    const normalMax = Math.max(...caps);
    return Math.ceil(normalMax);
  }, [sim, clip]);
  const shades = useMemo(() => (multi ? [] : sim.phases.filter((p) => p.phase !== "congestion_avoidance").slice(0, 160)), [sim, multi]);
  const marks = useMemo(() => sim.events.filter((e) => MARK_EVENTS.includes(e.event) && e.cwnd !== null && e.flow >= 0)
    .slice(0, 300).map((e) => ({ ...e, t: e.t, y: cap ? Math.min(e.cwnd!, cap) : e.cwnd })), [sim, cap]);
  const dur = sim.config.duration_s;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart margin={{ top: 8, right: 12, bottom: 0, left: -8 }} syncId="lab" syncMethod="value">
        <CartesianGrid vertical={false} />
        <XAxis type="number" dataKey="t" domain={[0, dur]} {...axis} tickFormatter={(v) => `${v}s`} allowDuplicatedCategory={false} />
        <YAxis {...axis} domain={[0, cap ?? "auto"]} allowDataOverflow={!!cap} width={48} />
        {shades.map((p, i) => (
          <ReferenceArea key={i} x1={p.start} x2={p.end} ifOverflow="hidden" strokeOpacity={0}
            fill={p.phase === "slow_start" ? C.blue : "#ec4899"} fillOpacity={p.phase === "slow_start" ? 0.1 : 0.13} />
        ))}
        <RTooltip content={<Tooltip />} cursor={{ stroke: C.fg3, strokeDasharray: "3 3" }} />
        {sim.cwnd.map((s) => {
          const color = multi ? flowColor(s.flow) : ALGO_COLOR[s.algorithm];
          const data = s.points.map(([t, c, th]) => ({ t, c, th }));
          return [
            <Line key={`c${s.flow}`} data={data} dataKey="c" type="stepAfter" stroke={color} strokeWidth={1.8}
              dot={false} isAnimationActive={false} name={`cwnd${multi ? ` · flow ${s.flow}` : ""}`} />,
            <Line key={`s${s.flow}`} data={data} dataKey="th" type="stepAfter" stroke={color} strokeOpacity={0.65}
              strokeWidth={1.2} strokeDasharray="4 3" dot={false} isAnimationActive={false}
              name={`ssthresh${multi ? ` · flow ${s.flow}` : ""}`} />,
          ];
        })}
        {showEvents && <Scatter data={marks} dataKey="y" shape={<EventShape />} isAnimationActive={false} name="events"
          onClick={(d: any) => onEvent?.(d.payload ?? d)} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function QueueChart({ sim, height = 190 }: { sim: SimResult; height?: number }) {
  const data = useMemo(() => sim.queue.map(([t, q]) => ({ t, q })), [sim]);
  const buf = sim.config.buffer_packets;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }} syncId="lab" syncMethod="value">
        <defs>
          <linearGradient id="qg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.emerald} stopOpacity={0.45} />
            <stop offset="100%" stopColor={C.emerald} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis type="number" dataKey="t" domain={[0, sim.config.duration_s]} {...axis} tickFormatter={(v) => `${v}s`} />
        <YAxis {...axis} domain={[0, Math.ceil(buf * 1.12)]} width={48} />
        <RTooltip content={<Tooltip unit="pkts" />} />
        <ReferenceLine y={buf} stroke={C.ruby} strokeDasharray="5 4" label={{ value: `buffer ${buf}`, fill: C.ruby, fontSize: 11, position: "insideTopRight" }} />
        <Area dataKey="q" type="stepAfter" stroke={C.emerald} strokeWidth={1.5} fill="url(#qg)" isAnimationActive={false} name="queue" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function RttChart({ sim, height = 190 }: { sim: SimResult; height?: number }) {
  const series = useMemo(() => {
    const by: Record<number, { t: number; r: number }[]> = {};
    sim.rtt.forEach(([t, f, r]) => (by[f] ??= []).push({ t, r }));
    return by;
  }, [sim]);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart margin={{ top: 8, right: 12, bottom: 0, left: -8 }} syncId="lab" syncMethod="value">
        <CartesianGrid vertical={false} />
        <XAxis type="number" dataKey="t" domain={[0, sim.config.duration_s]} {...axis} tickFormatter={(v) => `${v}s`} allowDuplicatedCategory={false} />
        <YAxis {...axis} width={48} domain={[0, "auto"]} />
        <RTooltip content={<Tooltip unit="ms" />} />
        <ReferenceLine y={sim.kpis.base_rtt_ms} stroke={C.fg3} strokeDasharray="4 4" label={{ value: "base RTT", fill: C.fg3, fontSize: 11, position: "insideBottomRight" }} />
        {Object.entries(series).map(([f, d]) => (
          <Line key={f} data={d} dataKey="r" stroke={flowColor(+f)} strokeWidth={1.4} dot={false} isAnimationActive={false} name={`RTT flow ${f}`} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function OverlayCwnd({ series, clip, height = 360 }: { series: CwndSeries[]; clip: boolean; height?: number }) {
  const cap = clip ? Math.ceil(Math.max(...series.map((s) => s.inflation_cap ?? Math.max(...s.points.map((p) => p[1])) * 1.05))) : undefined;
  const dur = Math.max(...series.map((s) => s.points[s.points.length - 1]?.[0] ?? 0));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <CartesianGrid vertical={false} />
        <XAxis type="number" dataKey="t" domain={[0, dur]} {...axis} tickFormatter={(v) => `${v}s`} allowDuplicatedCategory={false} />
        <YAxis {...axis} domain={[0, cap ?? "auto"]} allowDataOverflow={!!cap} width={48} />
        <RTooltip content={<Tooltip />} />
        <Legend wrapperStyle={{ fontSize: 12, color: C.fg2 }} iconType="plainline" />
        {series.map((s) => (
          <Line key={s.algorithm + s.flow} data={s.points.map(([t, c]) => ({ t, c }))} dataKey="c" type="stepAfter"
            stroke={ALGO_COLOR[s.algorithm]} strokeWidth={1.8} dot={false} isAnimationActive={false} name={ALGO_LABEL[s.algorithm]} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function MetricBars({ rows, metric, unit, digits = 2 }: { rows: any[]; metric: string; unit?: string; digits?: number }) {
  // Lightweight SVG bars: one bar per algorithm, value labels on top, 4px rounded data ends.
  const vals = rows.map((r) => (r[metric] ?? null) as number | null);
  const max = Math.max(...vals.map((v) => v ?? 0), 1e-9);
  const W = 360, H = 170, top = 22, bottom = 26, gap = 18;
  const bw = (W - gap * (rows.length + 1)) / rows.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={metric}>
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <line key={f} x1={0} x2={W} y1={top + (H - top - bottom) * (1 - f)} y2={top + (H - top - bottom) * (1 - f)} stroke={C.grid} />
      ))}
      <line x1={0} x2={W} y1={H - bottom} y2={H - bottom} stroke={C.border} />
      {rows.map((r, i) => {
        const v = vals[i];
        const h = ((v ?? 0) / max) * (H - top - bottom);
        const x = gap + i * (bw + gap);
        const y = H - bottom - h;
        return (
          <g key={r.algorithm}>
            <title>{`${ALGO_LABEL[r.algorithm]}: ${v == null ? "n/a" : v.toFixed(digits)}${unit ? " " + unit : ""}`}</title>
            <path d={h > 0 ? `M${x},${H - bottom} V${y + Math.min(4, h)} Q${x},${y} ${x + 4},${y} H${x + bw - 4} Q${x + bw},${y} ${x + bw},${y + Math.min(4, h)} V${H - bottom} Z` : ""}
              fill={ALGO_COLOR[r.algorithm]} />
            <text x={x + bw / 2} y={y - 6} textAnchor="middle" fontSize={11} fill={C.fg2} className="tnum">{v == null ? "—" : v.toFixed(digits)}</text>
            <text x={x + bw / 2} y={H - 8} textAnchor="middle" fontSize={11} fill={C.fg3}>{ALGO_LABEL[r.algorithm]}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function RiskTimeline({ points, threshold, horizon }: { points: [number, number, string, number | null][]; threshold: number; horizon: number }) {
  const data = points.map(([t, p, , a]) => ({ t, p, hit: a === 1 ? 1.02 : null }));
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <defs>
          <linearGradient id="rg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.ruby} stopOpacity={0.5} />
            <stop offset="50%" stopColor={C.amber} stopOpacity={0.25} />
            <stop offset="100%" stopColor={C.emerald} stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} />
        <ReferenceArea y1={0.6} y2={1.05} fill={C.ruby} fillOpacity={0.05} />
        <ReferenceArea y1={0.3} y2={0.6} fill={C.amber} fillOpacity={0.04} />
        <XAxis type="number" dataKey="t" domain={["dataMin", "dataMax"]} {...axis} tickFormatter={(v) => `${Number(v).toFixed(0)}s`} />
        <YAxis {...axis} domain={[0, 1.05]} ticks={[0, 0.3, 0.6, 1]} width={44} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
        <RTooltip content={<Tooltip labelFmt={(l: number) => `t = ${l.toFixed(2)} s · overflow within ${horizon * 1000} ms?`} />} />
        <ReferenceLine y={threshold} stroke={C.fg3} strokeDasharray="4 4" label={{ value: "decision threshold", fill: C.fg3, fontSize: 11, position: "insideTopLeft" }} />
        <Area dataKey="p" type="monotone" stroke={C.blue} strokeWidth={1.6} fill="url(#rg)" isAnimationActive={false} name="predicted risk" />
        <Scatter dataKey="hit" fill={C.ruby} shape={(p: any) => p.cy == null ? <g /> : <rect x={p.cx - 0.75} y={p.cy - 5} width={1.5} height={10} fill={C.ruby} />} name="overflow followed" isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
