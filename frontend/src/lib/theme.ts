export const C = {
  bg: "#0b0e14", bg2: "#0f121a", card: "#151a24", border: "#232a38", grid: "#1e2432",
  fg: "#e6e9ef", fg2: "#9aa3b5", fg3: "#646d80",
  blue: "#3b82f6", emerald: "#10b981", amber: "#f59e0b", ruby: "#ef4444", violet: "#8b5cf6", cyan: "#22d3ee",
};
// fixed categorical order — colour follows the algorithm, never its rank
export const ALGO_COLOR: Record<string, string> = {
  tahoe: "#3b82f6", reno: "#f97316", newreno: "#10b981", cubic: "#8b5cf6",
};
export const FLOW_COLORS = ["#3b82f6", "#f97316", "#10b981", "#8b5cf6", "#ec4899", "#14b8a6", "#eab308", "#a3a3a3", "#60a5fa", "#fb7185"];
export const flowColor = (f: number) => (f < 0 ? "#646d80" : FLOW_COLORS[f % FLOW_COLORS.length]);
// reserved status colours (always paired with a shape/label)
export const STATUS: Record<string, string> = {
  drop: "#ef4444", timeout: "#f59e0b", fast_retransmit: "#e6e9ef", partial_ack: "#22d3ee",
  enter_recovery: "#ec4899", exit_recovery: "#10b981", cwnd_reset: "#f59e0b", phase_change: "#9aa3b5",
};
export const EVENT_LABEL: Record<string, string> = {
  drop: "Packet drop", timeout: "Retransmission timeout", fast_retransmit: "Fast retransmit",
  partial_ack: "Partial ACK", enter_recovery: "Enter fast recovery", exit_recovery: "Exit fast recovery",
  cwnd_reset: "Window reset", phase_change: "Phase change",
};
