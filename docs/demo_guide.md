# 10-minute demonstration guide

1. **Start** (PowerShell): `.\.venv\Scripts\Activate.ps1; python -m streamlit run app.py`. Open the Overview: point
   out the topology and that no statistics are shown until something is run.
2. **Simulation Lab** (2 min): defaults (Reno, 10 Mbps, 20 ms, 35-packet buffer ≈ 1 BDP) → *Run*. Show slow-start
   shading, the sawtooth, fast-retransmit markers, and the BDP panel. *Event timeline* tab → click a fast retransmit →
   read the rule-based explanation. Press *Replay last run* to show reproducibility.
3. **Packet Visualizer** (2 min): *Load demo trace* → *Jump to: first drop* → *Play*. Show queue filling, the drop,
   duplicate ACKs, fast retransmit, partial ACK (NewReno) and the sender's cwnd/ssthresh at each step.
4. **Scenario Lab** (2 min): *Multiple losses in one window* → Run: NewReno 1 recovery + 2 partial ACKs vs Reno
   needing extra reductions/timeout. Then *High bandwidth-delay product*: CUBIC regains its window faster.
   Point out "expected vs observed" checks are computed, not hard-coded.
5. **Algorithm Comparison** (1 min): all four algorithms, same seed; table, bar charts, data-driven notes + caveat.
6. **Learning Centre** (1 min): one lesson's *Try it*, a quiz question, the prediction challenge.
7. **AI Congestion Prediction** (1 min): evaluation tab (held-out configurations, baselines, calibration), then the
   risk timeline on a run. Stress: read-only, never controls TCP.
8. **Validation / Reports** (1 min): rule probes all pass; real Linux trace comparison; download the HTML report.

Likely questions: *Why does cwnd spike during recovery?* RFC 5681/6582 window inflation (+1 per dup ACK); clipped by
default. *Why can CUBIC time out?* No SACK in the model; many losses in one window with the Impatient NewReno timer.
