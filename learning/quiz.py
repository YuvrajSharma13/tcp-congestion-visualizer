"""Multiple-choice quiz and the prediction challenge definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    prompt: str
    options: tuple[str, ...]
    answer: int
    explanation: str


QUESTIONS: tuple[Question, ...] = (
    Question("During slow start, how does cwnd change over one RTT with no loss?",
             ("It grows by 1 segment", "It roughly doubles", "It stays constant", "It grows by 1/cwnd"),
             1, "Each ACK of new data adds 1 segment; a full window of ACKs therefore doubles cwnd (RFC 5681 §3.1)."),
    Question("What triggers a fast retransmit?",
             ("One duplicate ACK", "The retransmission timer", "Three duplicate ACKs", "A full receive window"),
             2, "Three duplicate ACKs are taken as evidence of loss rather than reordering (RFC 5681 §3.2)."),
    Question("After three duplicate ACKs, what does TCP Tahoe set cwnd to?",
             ("ssthresh + 3", "1 segment", "Half of cwnd", "Unchanged"),
             1, "Tahoe has no fast recovery: it retransmits and restarts slow start from 1 segment."),
    Question("When Reno enters fast recovery with ssthresh = 10, what is cwnd?",
             ("10", "13", "5", "1"),
             1, "cwnd = ssthresh + 3, because the three duplicate ACKs show three segments have left the network."),
    Question("Three segments from the same window are lost. Which algorithm repairs them in one recovery episode?",
             ("Tahoe", "Reno", "NewReno", "None of them"),
             2, "NewReno stays in fast recovery on partial ACKs and retransmits each hole (RFC 6582)."),
    Question("What is a partial ACK?",
             ("An ACK for part of a segment", "An ACK that acknowledges new data but not everything sent before "
              "recovery began", "A duplicate ACK", "An ACK that is lost"),
             1, "It advances the cumulative ACK but stays below `recover`, proving another segment was lost."),
    Question("Why does an RTO hurt throughput more than a fast retransmit?",
             ("It doubles cwnd", "It waits at least the RTO and then restarts from cwnd = 1",
              "It disables slow start", "It resets ssthresh to infinity"),
             1, "The sender idles until the timer fires, then cwnd = 1 and the RTO doubles (RFC 6298 back-off)."),
    Question("A 10 Mbps link with an 80 ms RTT and 1500-byte packets has a BDP of about...",
             ("8 packets", "67 packets", "667 packets", "800 packets"),
             1, "10e6 x 0.08 / (8 x 1500) ≈ 66.7 packets must be in flight to fill the link."),
    Question("CUBIC's multiplicative decrease factor beta is...",
             ("0.5", "0.7", "0.875", "1.0"),
             1, "RFC 9438 uses beta_cubic = 0.7, so CUBIC keeps 70% of its window after a loss."),
    Question("In CUBIC's W(t) = C(t - K)^3 + W_max, what happens around t = K?",
             ("cwnd is at its minimum", "cwnd plateaus near W_max", "cwnd resets to 1", "ssthresh doubles"),
             1, "K is the time to climb back to W_max; growth flattens there (concave), then turns convex."),
    Question("Which samples does Karn's algorithm exclude from RTT estimation?",
             ("Samples larger than the RTO", "Samples from retransmitted segments",
              "Samples during slow start", "Duplicate ACKs"),
             1, "An ACK for a retransmitted segment is ambiguous: it may answer the original or the copy."),
    Question("Jain's fairness index for two flows with 9 Mbps and 1 Mbps is...",
             ("0.5", "0.61", "0.9", "1.0"),
             1, "(9+1)^2 / (2 x (81+1)) = 100/164 ≈ 0.61."),
    Question("A very small router buffer (far below one BDP) usually causes...",
             ("Higher queueing delay", "Lower link utilisation after window reductions",
              "Fewer packet drops", "Larger cwnd"),
             1, "With little buffering, halving cwnd leaves less than a BDP in flight, so the link idles."),
    Question("Random (non-congestion) loss on a link makes loss-based TCP...",
             ("Ignore it", "Reduce its window as if the network were congested", "Increase its window",
              "Switch to UDP"),
             1, "Loss-based TCP cannot tell the causes apart; goodput falls roughly with 1/sqrt(p) for Reno."),
)


@dataclass(frozen=True)
class Challenge:
    id: str
    title: str
    change: str
    param: str
    base_value: float
    new_value: float
    algorithm: str = "reno"


CHALLENGES: tuple[Challenge, ...] = (
    Challenge("buffer", "Shrink the buffer", "Buffer: 35 → 4 packets", "buffer_packets", 35, 4),
    Challenge("loss", "Add random loss", "Random loss: 0% → 1%", "loss_prob", 0.0, 0.01),
    Challenge("delay", "Increase propagation delay", "One-way delay: 20 → 80 ms", "delay_ms", 20, 80),
    Challenge("bandwidth", "Double the bandwidth", "Bandwidth: 10 → 20 Mbps", "bandwidth_mbps", 10, 20),
)

PREDICTION_METRICS = {
    "goodput_mbps": "Goodput",
    "avg_rtt_ms": "Average RTT",
    "loss_pct": "Packet loss",
}
