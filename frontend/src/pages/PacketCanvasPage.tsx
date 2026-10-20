import { useState } from "react";
import { Boxes, Info, Play } from "lucide-react";
import type { SimState } from "../App";
import PacketCanvas from "../components/PacketCanvas";
import { Card, Empty, ErrorBox, Spinner } from "../components/ui";
import { ConfigPanel } from "./SimulationLab";

const DEMO = { algorithm: "newreno" as const, algorithms: null, n_flows: 1, bandwidth_mbps: 5, delay_ms: 15, buffer_packets: 10,
  loss_rate: 0, duration_s: 8, initial_ssthresh: 64, playback: true, playback_start_s: 0, playback_window_s: 3 };

export default function PacketCanvasPage({ s }: { s: SimState }) {
  const { sim, loading, error, run, params, setParams } = s;
  const [start, setStart] = useState(0);
  const pb = sim?.playback;
  const load = (t: number) => { setStart(t); run({ playback: true, playback_start_s: t }); };
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Packet flow, frame by frame</h1>
          <p className="mt-1 max-w-3xl text-sm text-fg-2">A dumbbell topology animated at 60 FPS from the simulator's packet log: each packet's enqueue,
            serialization, propagation, drop and ACK times are real timestamps from the trace — nothing is decorative.</p>
        </div>
        <div className="flex items-end gap-2">
          <label className="text-xs text-fg-3">window start (s)
            <input type="number" min={0} step={0.5} value={start} onChange={(e) => setStart(parseFloat(e.target.value || "0"))}
              className="tnum mt-1 block w-24 rounded-lg border border-ink-600 bg-ink-900 px-2 py-1.5 font-mono text-sm text-fg" />
          </label>
          <button className="btn-ghost" onClick={() => load(start)} disabled={loading}>Load 3 s window</button>
          <button className="btn-primary" onClick={() => { setParams({ ...params, ...DEMO }); setStart(0); run(DEMO); }} disabled={loading}>
            <Play size={15} />Demo: buffer overflow
          </button>
        </div>
      </div>
      <ErrorBox error={error} />
      {loading && <div className="card grid h-[400px] place-items-center"><Spinner label="Simulating and extracting the packet trace…" /></div>}
      {!loading && !pb && (
        <Empty icon={<Boxes size={22} />} title="No packet trace loaded">
          Run a simulation (or the overflow demo) to animate it. Packet-level traces are recorded for runs up to ~150k packets.
        </Empty>
      )}
      {!loading && pb && sim && (
        <>
          <PacketCanvas pb={pb} algorithms={sim.flows.map((f) => f.algorithm)} onJumpWindow={(t) => load(t)} />
          <div className="grid items-start gap-5 lg:grid-cols-[1fr_340px]">
            <Card title="Legend">
              <ul className="grid gap-2 text-sm text-fg-2 sm:grid-cols-2">
                <li>■ solid block — data segment (colour = flow)</li>
                <li>□ outlined block — retransmission</li>
                <li>◀ triangle — cumulative ACK on the reverse path</li>
                <li><span className="text-ruby">DROP</span> — arrived at a full buffer (tail drop)</li>
                <li><span className="text-ruby">LOST</span> — random / burst loss on the link</li>
                <li>bar under router — serialization progress</li>
              </ul>
              {pb.truncated && <p className="mt-3 flex items-center gap-1.5 text-xs text-amber"><Info size={13} />Window truncated to the first 4,000 packets.</p>}
            </Card>
            <Card title="Configuration"><ConfigPanel s={s} compact /></Card>
          </div>
        </>
      )}
    </div>
  );
}
