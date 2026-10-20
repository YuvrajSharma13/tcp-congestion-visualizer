import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import { ALGO_LABEL, type Playback } from "../lib/api";
import { C, EVENT_LABEL, STATUS, flowColor } from "../lib/theme";

/**
 * 60 FPS canvas renderer of a recorded simulation window.
 * Every position is computed from the packet's logged timestamps
 * (send, enqueue, tx start/end, receive, drop) — no decorative motion.
 */

const SPEEDS = [0.25, 0.5, 1, 2, 4];
const H = 400;

type Row = Playback["packets"][number];
const I = { uid: 0, flow: 1, seq: 2, kind: 3, ts: 4, tenq: 5, tx0: 6, tx1: 7, trx: 8, tdrop: 9, cause: 10 } as const;

function lastBefore<T>(arr: T[], t: number, key: (x: T) => number): number {
  let lo = 0, hi = arr.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (key(arr[mid]) <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

export default function PacketCanvas({ pb, algorithms, onJumpWindow }: {
  pb: Playback; algorithms: string[]; onJumpWindow?: (t: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const tRef = useRef(pb.t0);
  const playingRef = useRef(false);
  const speedRef = useRef(1);
  const [tUi, setTUi] = useState(pb.t0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [width, setWidth] = useState(1000);

  // one base-RTT of simulated time per 2 s of wall time at 1x (slow motion, so packets are visible)
  const baseRate = useMemo(() => Math.max((2 * pb.delay_s + pb.tx_time_s) / 2, pb.tx_time_s * 4, 0.002), [pb]);

  const times = useMemo(() => {
    const s = new Set<number>();
    for (const p of pb.packets) for (const k of [I.ts, I.tx0, I.tx1, I.trx, I.tdrop]) { const v = p[k] as number | null; if (v != null) s.add(v); }
    for (const a of pb.acks) s.add(a[3]);
    return Array.from(s).sort((a, b) => a - b);
  }, [pb]);
  const cwndByFlow = useMemo(() => {
    const m: Record<number, Playback["cwnd"]> = {};
    for (const r of pb.cwnd) (m[r[1]] ??= []).push(r);
    return m;
  }, [pb]);
  const drops = useMemo(() => pb.packets.filter((p) => p[I.tdrop] != null).map((p) => p[I.tdrop] as number).sort((a, b) => a - b), [pb]);
  const ccEvents = useMemo(() => pb.events.filter((e) => e[1] !== "send" && e[1] !== "phase_change"), [pb]);

  useEffect(() => { tRef.current = pb.t0; setTUi(pb.t0); playingRef.current = false; setPlaying(false); }, [pb]);
  useEffect(() => { speedRef.current = speed; }, [speed]);

  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(640, e.contentRect.width)));
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  const draw = useCallback((t: number) => {
    const cv = canvasRef.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const W = width;
    if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext("2d")!;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);

    const mid = 165, ackY = 318;
    const sx = 70, qx0 = W * 0.2, qx1 = W * 0.42, rx = W * 0.47, lx1 = W * 0.84, recvX = W * 0.9;
    const n = pb.n_flows;
    const senderY = (i: number) => mid + (i - (n - 1) / 2) * Math.min(56, 220 / Math.max(n, 1));
    const wallToSim = baseRate; // sim seconds per wall second at 1x
    const fx = 0.9 * wallToSim; // visual effect duration in sim time

    // ---- static topology
    g.lineWidth = 1;
    for (let i = 0; i < n; i++) {
      const y = senderY(i);
      g.strokeStyle = "#232a38"; g.beginPath(); g.moveTo(sx + 46, y); g.bezierCurveTo(qx0 - 60, y, qx0 - 60, mid, qx0 - 6, mid); g.stroke();
    }
    // link wire with flowing dash
    const grad = g.createLinearGradient(rx, 0, lx1, 0);
    grad.addColorStop(0, "rgba(59,130,246,.55)"); grad.addColorStop(1, "rgba(59,130,246,.15)");
    g.strokeStyle = grad; g.lineWidth = 3; g.beginPath(); g.moveTo(rx + 26, mid); g.lineTo(lx1, mid); g.stroke();
    g.setLineDash([2, 10]); g.lineDashOffset = -((t / wallToSim) * 40) % 12;
    g.strokeStyle = "rgba(230,233,239,.25)"; g.lineWidth = 1; g.beginPath(); g.moveTo(rx + 26, mid); g.lineTo(lx1, mid); g.stroke();
    g.setLineDash([]);
    // reverse ACK path
    g.strokeStyle = "#232a38"; g.setLineDash([4, 6]); g.beginPath();
    g.moveTo(recvX + 30, mid + 28); g.lineTo(recvX + 30, ackY); g.lineTo(sx, ackY); g.lineTo(sx, senderY(n - 1) + 18); g.stroke(); g.setLineDash([]);

    g.font = "11px Inter, system-ui, sans-serif"; g.textAlign = "center";
    g.fillStyle = C.fg3;
    g.fillText(`FIFO drop-tail buffer · ${pb.buffer_packets} pkts`, (qx0 + qx1) / 2, mid - 34);
    g.fillText(`bottleneck link · ${(pb.delay_s * 1000).toFixed(1)} ms propagation`, (rx + lx1) / 2, mid - 16);
    g.fillText("cumulative ACKs (reverse path)", (sx + recvX) / 2, ackY + 18);

    // senders
    for (let i = 0; i < n; i++) {
      const y = senderY(i);
      roundRect(g, sx - 46, y - 17, 92, 34, 8, "#151a24", flowColor(i));
      g.fillStyle = C.fg; g.textAlign = "center"; g.font = "600 11px Inter, system-ui";
      g.fillText(`S${i} · ${ALGO_LABEL[algorithms[i]] ?? ""}`, sx, y + 4);
    }
    // queue box
    roundRect(g, qx0 - 4, mid - 22, qx1 - qx0 + 8, 44, 8, "#0f121a", "#2f3849");
    // router
    g.beginPath(); g.arc(rx, mid, 24, 0, Math.PI * 2); g.fillStyle = "#151a24"; g.fill();
    g.lineWidth = 1.5; g.strokeStyle = "#9aa3b5"; g.stroke();
    g.fillStyle = C.fg3; g.font = "10px Inter"; g.fillText("router", rx, mid + 40);
    // receiver
    roundRect(g, recvX - 34, mid - 28, 92, 56, 10, "#151a24", "#9aa3b5");
    g.fillStyle = C.fg; g.font = "600 11px Inter"; g.fillText("Receiver", recvX + 12, mid + 4);

    // ---- dynamic state from timestamps
    const queued: Row[] = [];
    let delivered = 0, droppedSoFar = 0, recvFlash: string | null = null, tagged = 0;
    for (const p of pb.packets) {
      const ts = p[I.ts] as number, tenq = p[I.tenq] as number | null, tx0 = p[I.tx0] as number | null,
        tx1 = p[I.tx1] as number | null, trx = p[I.trx] as number | null, tdrop = p[I.tdrop] as number | null;
      if (ts > t) continue;
      const color = flowColor(p[I.flow] as number);
      const retx = p[I.kind] !== "new" && p[I.kind] !== "cross";
      if (tdrop != null && tdrop <= t) droppedSoFar++;
      if (trx != null && trx <= t) {
        delivered++;
        if (t - trx < fx * 0.4) recvFlash = color;
        continue;
      }
      // overflow drop at the buffer entrance
      if (tenq == null && tdrop != null) {
        const age = (t - tdrop) / fx;
        if (age >= 0 && age < 1) drawDrop(g, qx0 - 18, mid, age, color, tagged++ === 0 ? "DROP · buffer full" : "");
        continue;
      }
      if (tenq != null && tenq <= t && (tx0 == null || tx0 > t)) { queued.push(p); continue; }
      if (tx0 != null && tx0 <= t && tx1 != null && tx1 > t) {
        const f = (t - tx0) / Math.max(tx1 - tx0, 1e-9);
        pkt(g, rx - 7, mid - 6, 14, 12, color, retx);
        g.fillStyle = "rgba(230,233,239,.75)"; g.fillRect(rx - 14, mid + 14, 28 * f, 2);
        continue;
      }
      if (tx1 != null && tx1 <= t) {
        if (tdrop != null && trx == null) { // lost on the wire
          const age = (t - tdrop) / fx;
          if (age >= 0 && age < 1) drawDrop(g, rx + 60, mid, age, color, tagged++ === 0 ? `LOST · ${p[I.cause]}` : "");
          continue;
        }
        if (trx != null) {
          const f = pb.delay_s > 0 ? (t - tx1) / pb.delay_s : 1;
          const x = rx + 26 + (lx1 - rx - 26) * Math.min(Math.max(f, 0), 1);
          pkt(g, x - 7, mid - 6, 14, 12, color, retx);
        }
      }
    }
    // queue contents, head next to the router
    const B = pb.buffer_packets;
    const slots = Math.min(B, 40);
    const sw = (qx1 - qx0) / slots;
    if (B <= 40) {
      for (let k = 0; k < slots; k++) { g.strokeStyle = "#1b2130"; g.strokeRect(qx1 - (k + 1) * sw + 1, mid - 16, sw - 2, 32); }
      queued.forEach((p, k) => pkt(g, qx1 - (k + 1) * sw + 1.5, mid - 15, sw - 3, 30, flowColor(p[I.flow] as number), p[I.kind] !== "new"));
    } else {
      const frac = Math.min(queued.length / B, 1);
      const qgrad = g.createLinearGradient(qx1 - frac * (qx1 - qx0), 0, qx1, 0);
      qgrad.addColorStop(0, "rgba(16,185,129,.35)"); qgrad.addColorStop(1, "rgba(16,185,129,.85)");
      g.fillStyle = qgrad; g.fillRect(qx1 - frac * (qx1 - qx0), mid - 15, frac * (qx1 - qx0), 30);
    }
    const qFrac = queued.length / B;
    g.font = "600 12px JetBrains Mono, Consolas, monospace"; g.textAlign = "center";
    g.fillStyle = qFrac >= 1 ? C.ruby : qFrac > 0.75 ? C.amber : C.fg;
    g.fillText(`${queued.length}/${B}`, (qx0 + qx1) / 2, mid + 40);
    if (qFrac >= 1) { g.shadowColor = C.ruby; g.shadowBlur = 18; g.strokeStyle = C.ruby; g.strokeRect(qx0 - 4, mid - 22, qx1 - qx0 + 8, 44); g.shadowBlur = 0; }

    if (recvFlash) { g.shadowColor = recvFlash; g.shadowBlur = 24; g.strokeStyle = recvFlash; g.lineWidth = 2; g.strokeRect(recvX - 34, mid - 28, 92, 56); g.shadowBlur = 0; g.lineWidth = 1; }

    // ACKs on the reverse path
    let ackCount = 0;
    for (const [flow, ack, s, a] of pb.acks) {
      if (s > t || a <= t) continue;
      ackCount++;
      const f = (t - s) / Math.max(a - s, 1e-9);
      // path: down from receiver, then left along ackY
      const total = (ackY - mid - 28) + (recvX + 30 - sx);
      const d = f * total;
      let x: number, y: number;
      if (d < ackY - mid - 28) { x = recvX + 30; y = mid + 28 + d; } else { x = recvX + 30 - (d - (ackY - mid - 28)); y = ackY; }
      g.fillStyle = flowColor(flow);
      g.beginPath(); g.moveTo(x - 6, y); g.lineTo(x + 3, y - 4.5); g.lineTo(x + 3, y + 4.5); g.closePath(); g.fill();
      if (ackCount < 4 && pb.acks.length < 2500) { g.fillStyle = C.fg3; g.font = "9px JetBrains Mono, monospace"; g.fillText(`${ack}`, x, y - 8); }
    }

    // HUD: sender state at t
    g.textAlign = "left";
    let hy = 22;
    for (let f = 0; f < n; f++) {
      const rows = cwndByFlow[f] ?? [];
      const i = lastBefore(rows, t, (r) => r[0]);
      if (i < 0) continue;
      const r = rows[i];
      g.fillStyle = flowColor(f); g.fillRect(14, hy - 9, 8, 8);
      g.fillStyle = C.fg; g.font = "11px JetBrains Mono, Consolas, monospace";
      g.fillText(`flow ${f}  cwnd ${r[2].toFixed(2).padStart(7)}  ssthresh ${r[3].toFixed(1).padStart(7)}  ${String(r[4]).replace("_", " ")}`, 28, hy);
      hy += 18;
    }
    g.fillStyle = C.fg3; g.textAlign = "right"; g.font = "11px JetBrains Mono, monospace";
    g.fillText(`t = ${t.toFixed(5)} s`, W - 14, 22);
    g.fillText(`delivered ${delivered} · dropped ${droppedSoFar} · ACKs in flight ${ackCount}`, W - 14, 40);

    // event toast
    const ei = lastBefore(ccEvents, t, (e) => e[0]);
    if (ei >= 0 && t - ccEvents[ei][0] < 1.6 * wallToSim) {
      const e = ccEvents[ei];
      const label = `${EVENT_LABEL[e[1]] ?? e[1]} · flow ${e[2]}${e[3] >= 0 ? ` · seg ${e[3]}` : ""}`;
      g.font = "600 12px Inter"; const w = g.measureText(label).width + 28;
      const alpha = 1 - (t - e[0]) / (1.6 * wallToSim);
      g.globalAlpha = Math.max(alpha, 0.15);
      roundRect(g, W / 2 - w / 2, H - 46, w, 30, 15, "#0b0e14", STATUS[e[1]] ?? C.fg2);
      g.fillStyle = STATUS[e[1]] ?? C.fg; g.textAlign = "center"; g.fillText(label, W / 2, H - 27);
      g.globalAlpha = 1;
    }
  }, [pb, width, baseRate, algorithms, cwndByFlow, ccEvents]);

  // animation loop
  useEffect(() => {
    let raf = 0, last = performance.now(), lastUi = 0;
    const tick = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.1);
      last = now;
      if (playingRef.current) {
        tRef.current += dt * baseRate * speedRef.current;
        if (tRef.current >= pb.t1) { tRef.current = pb.t1; playingRef.current = false; setPlaying(false); }
      }
      draw(tRef.current);
      if (now - lastUi > 90) { setTUi(tRef.current); lastUi = now; }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [draw, baseRate, pb.t1]);

  const seek = (t: number) => { tRef.current = Math.min(Math.max(t, pb.t0), pb.t1); setTUi(tRef.current); };
  const step = (dir: 1 | -1) => {
    playingRef.current = false; setPlaying(false);
    const t = tRef.current;
    if (dir > 0) { const n = times.find((x) => x > t + 1e-12); if (n != null) seek(n); }
    else { const i = lastBefore(times, t - 1e-12, (x) => x); if (i >= 0) seek(times[i]); }
  };
  const toggle = () => {
    if (tRef.current >= pb.t1) seek(pb.t0);
    playingRef.current = !playingRef.current; setPlaying(playingRef.current);
  };
  const nextDrop = () => {
    const n = drops.find((d) => d > tRef.current + 1e-9);
    if (n != null) seek(Math.max(n - 2 * baseRate, pb.t0));
    else if (onJumpWindow) onJumpWindow(pb.t1);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.code === "Space") { e.preventDefault(); toggle(); }
      if (e.code === "ArrowRight") step(1);
      if (e.code === "ArrowLeft") step(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div>
      <div ref={wrapRef} className="overflow-hidden rounded-xl border border-ink-600 bg-[radial-gradient(800px_300px_at_50%_0%,rgba(59,130,246,.07),transparent)] bg-ink-900">
        <canvas ref={canvasRef} style={{ width, height: H, display: "block" }} aria-label="Packet flow animation" />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button className="btn-ghost" onClick={() => { seek(pb.t0); playingRef.current = false; setPlaying(false); }} title="Reset"><RotateCcw size={15} /></button>
        <button className="btn-ghost" onClick={() => step(-1)} title="Step back (←)"><ChevronLeft size={16} /></button>
        <button className="btn-primary w-28" onClick={toggle}>{playing ? <><Pause size={15} />Pause</> : <><Play size={15} />Play</>}</button>
        <button className="btn-ghost" onClick={() => step(1)} title="Step forward (→)"><ChevronRight size={16} /></button>
        <button className="btn-ghost text-xs" onClick={nextDrop} title="Jump to the next drop"><SkipForward size={14} />Next drop</button>
        <div className="ml-auto flex items-center gap-1 rounded-lg border border-ink-600 bg-ink-900 p-1">
          {SPEEDS.map((s) => (
            <button key={s} onClick={() => setSpeed(s)} className={clsx("tnum rounded-md px-2 py-1 font-mono text-xs",
              s === speed ? "bg-blue text-white" : "text-fg-3 hover:text-fg")}>{s}×</button>
          ))}
        </div>
      </div>
      <input type="range" className="slider mt-3" min={pb.t0} max={pb.t1} step={(pb.t1 - pb.t0) / 2000} value={tUi}
        onChange={(e) => { playingRef.current = false; setPlaying(false); seek(parseFloat(e.target.value)); }} />
      <div className="mt-1 flex justify-between font-mono text-[11px] text-fg-3">
        <span>{pb.t0.toFixed(3)} s</span>
        <span>1× = one base RTT per 2 s of wall time · space = play/pause · ←/→ = step</span>
        <span>{pb.t1.toFixed(3)} s</span>
      </div>
    </div>
  );
}

function roundRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number, fill: string, stroke: string) {
  g.beginPath(); g.roundRect(x, y, w, h, r); g.fillStyle = fill; g.fill(); g.lineWidth = 1.5; g.strokeStyle = stroke; g.stroke(); g.lineWidth = 1;
}

function pkt(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, color: string, hollow: boolean) {
  g.beginPath(); g.roundRect(x, y, w, h, 2.5);
  if (hollow) { g.lineWidth = 2; g.strokeStyle = color; g.stroke(); g.lineWidth = 1; }
  else { g.shadowColor = color; g.shadowBlur = 8; g.fillStyle = color; g.fill(); g.shadowBlur = 0; }
}

function drawDrop(g: CanvasRenderingContext2D, x: number, y: number, age: number, color: string, tag: string) {
  // red glow, small bounce, then shards falling off-screen
  const fall = age * age * 200;
  const bounce = Math.sin(Math.min(age * 4, 1) * Math.PI) * 10;
  g.save();
  g.globalAlpha = 1 - age * 0.85;
  if (age < 0.25) {
    g.shadowColor = "#ef4444"; g.shadowBlur = 22;
    g.fillStyle = "#ef4444"; g.beginPath(); g.roundRect(x - 7, y - 6 - bounce, 14, 12, 2.5); g.fill();
    g.shadowBlur = 0; g.strokeStyle = color; g.strokeRect(x - 7, y - 6 - bounce, 14, 12);
  } else {
    for (let k = 0; k < 4; k++) {
      const dx = (k - 1.5) * 8 * age * 3, rot = (k - 1.5) * age * 4;
      g.save(); g.translate(x + dx, y + fall * (0.8 + k * 0.1)); g.rotate(rot);
      g.fillStyle = k % 2 ? "#ef4444" : color; g.fillRect(-3.5, -3, 7, 6); g.restore();
    }
  }
  if (tag) { g.font = "700 10px Inter, system-ui"; g.textAlign = "center"; g.fillStyle = "#ef4444"; g.fillText(tag, x, y - 18 - bounce); }
  g.restore();
}
