# TCP Congestion Control Visualizer

**An interactive TCP simulation, performance analysis and congestion-prediction platform**
BCSE308P Computer Networks project — Yuvraj Sharma (24BCE2337), Arsh Vardhan Singh (24BCE2119), VIT.

A Python discrete-event simulator of TCP **Tahoe, Reno, NewReno and CUBIC** sharing a drop-tail bottleneck, with a
Streamlit dashboard that shows cwnd, ssthresh, RTT, throughput, queue occupancy and every loss/recovery event —
all drawn from the simulator's own event trace.

## Features

* Discrete-event engine with deterministic tie-breaking; fixed seed ⇒ identical trace.
* Bottleneck link (bandwidth, propagation delay, serialization, FIFO drop-tail buffer), random loss, loss bursts,
  scripted drops, optional cross traffic, multiple flows with per-flow algorithm and start time.
* RFC 6298 RTO with Karn's algorithm and back-off; cumulative-ACK receiver with reassembly.
* Four algorithms as separate classes behind one interface (RFC 5681, 6582, 9438).
* Dashboard pages: Overview · Simulation Lab · Packet Visualizer (event-by-event playback) · Algorithm Comparison ·
  Scenario Lab (10 scenarios with expected-vs-observed checks) · Sensitivity Analysis (multi-seed, 95% CI) ·
  Experiments & Reports (CSV/JSON/HTML/PNG/SVG, SQLite history, presets) · Learning Centre (lessons, quiz,
  prediction challenge) · AI Congestion Prediction · Validation (RFC rule probes, trace audits, real Linux traces).
* Rule-based explanations of every congestion event; BDP calculator; Jain's fairness index.
* Optional ML module (scikit-learn) predicting buffer overflow in the next 200 ms, evaluated on held-out network
  configurations against baselines. **It never influences the simulated TCP.**

## Architecture

```
 Configuration ──► Simulator (events · link/queue · receiver · RTO) ◄──► Algorithm module
  (validated)             │                                          (Tahoe/Reno/NewReno/CUBIC)
                          ▼
                  SimulationResult (event log, cwnd, queue, RTT, deliveries, samples)
                          │
     ┌────────────┬───────┴──────┬─────────────┬────────────┬──────────────┐
  metrics    charts/playback   analytics    exports/report   validation   ML (read-only)
                          ▼
                  Streamlit dashboard (app.py, ui/)
```
Details: [docs/architecture.md](docs/architecture.md) · assumptions & units: [docs/simulation_assumptions.md](docs/simulation_assumptions.md) · validation results: [docs/validation.md](docs/validation.md) · demo script: [docs/demo_guide.md](docs/demo_guide.md).

## Technologies

Python 3.10+ · Streamlit · Plotly · NumPy · Pandas · scikit-learn · Matplotlib · pytest · SQLite (stdlib).

## Web app (FastAPI + React) — recommended

The primary interface is a React + Tailwind dashboard (`frontend/`) talking to a FastAPI backend (`api/`).

Prerequisites: Python 3.10+ and **Node.js 18+**.

```powershell
.\run.ps1            # creates .venv, installs deps, starts API :8000 and UI :5173, opens the browser
.\run.ps1 -Test      # same, but runs the 160-test suite first
```
`run.bat` does the same from cmd; `./run.sh` on macOS/Linux/WSL. Manual equivalent:

```powershell
python -m uvicorn api.main:app --port 8000          # terminal 1  (API docs: http://localhost:8000/docs)
cd frontend; npm install; npm run dev               # terminal 2  (UI: http://localhost:5173, /api proxied)
```
Single-port option: `cd frontend; npm run build`, then only the API — it serves the built UI at http://localhost:8000.

| Endpoint | Purpose |
|---|---|
| `POST /api/simulate` | KPIs, cwnd/ssthresh/queue/RTT series, explained events, packet-level playback trace |
| `POST /api/compare` | all four algorithms under identical conditions + data-driven notes |
| `GET /api/scenarios`, `POST /api/scenarios/{id}/run` | 9 preset experiments with expected-vs-observed checks (10th = custom config) |
| `POST /api/predict` | overflow-risk timeline from the trained model (read-only) |
| `GET /api/validation` | RFC rule probes + trace audit |

`loss_rate` is in percent. Invalid configurations return HTTP 422 with every problem listed.

UI pages: Simulation Lab · Packet Canvas (60 FPS, drawn from real packet timestamps; play/pause/step/scrub, 0.25×–4×) ·
Algorithm Comparison · Scenario Lab · AI Predictor · Validation & RFCs.

## Install and run the classic Streamlit dashboard (Windows PowerShell)

Prerequisites: Python 3.10 or newer from python.org (tick "Add to PATH").

```powershell
cd tcp-congestion-visualizer
py -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q                    # 160 tests
python -m streamlit run app.py         # opens http://localhost:8501
```
(macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`, then the same commands.)

## Machine-learning model

A trained model is bundled in `models/`. To regenerate data and retrain (≈1–3 minutes):
```powershell
python -m ml.train --configs 48 --seeds 1 2
```
or use *AI Congestion Prediction → Train / retrain*. Label: ≥1 buffer-overflow drop in the next 200 ms; features
use only the preceding 200 ms; train/test split by network configuration. Bundled model on 12 held-out
configurations: ROC-AUC 0.913, F1 0.696 (random forest) vs 0.616/0.456 for a queue-threshold rule.

## Example scenarios

Baseline · increasing random loss · shallow buffer · burst losses → RTO · multiple losses in one window (Reno vs
NewReno) · high BDP (Reno vs CUBIC) · two competing flows · four different algorithms sharing · low-bandwidth/
high-delay · custom. All are one click in the Scenario Lab.

## Optional real-network traces (Linux/WSL)

`tools/capture_ss_trace.sh <server> <seconds> <reno|cubic> out.txt` records `ss -tin` while iperf3 runs; import it
on the Validation page. Two real Linux captures are bundled in `data/real_traces/`. The app never modifies the
operating system's TCP stack.

## Troubleshooting

* `streamlit` not found → activate the venv and use `python -m streamlit run app.py`.
* "This configuration cannot be simulated" → the message lists each invalid value (e.g. too many packets: lower
  bandwidth × duration).
* Packet Visualizer shows no trace → enable *Record per-packet events* (Advanced) or use *Load demo trace*.
* ML page says the model cannot be loaded → retrain (scikit-learn version differs).
* PNG export uses Matplotlib (Plotly's own image export would need Chrome); the camera icon on each chart also works.
* Port in use → `python -m streamlit run app.py --server.port 8502`.

## Known limitations

Segment-level model; no SACK, delayed ACKs, pacing, HyStart++, ECN/AQM, connection setup or ACK loss; CUBIC uses
NewReno-style recovery; fast-recovery window inflation follows the RFCs literally (charts clip the spikes);
results show modelled behaviour, not a real OS stack. See [docs/simulation_assumptions.md](docs/simulation_assumptions.md).

## References

RFC 5681 (TCP Congestion Control) · RFC 6582 (NewReno) · RFC 6298 (RTO) · RFC 9438 (CUBIC) · Jacobson 1988 ·
Ha, Rhee & Xu 2008 · Jain, Chiu & Hawe 1984 · Fall & Floyd 1996 · Mathis et al. 1997.
