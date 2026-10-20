"""Persistent experiment history and named presets in a local SQLite file.

* Default location: ``data/experiments.db`` inside the project folder (created
  on first use).  Nothing leaves the machine.
* Only configurations and summary metrics are stored - full event traces live
  in the dashboard session (session history) and can be exported as CSV.
* Every operation opens and closes its own connection, which keeps the store
  safe to use from Streamlit's script reruns.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd

from config import defaults as D
from config.validation import SimulationConfig

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "experiments.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    label TEXT,
    algorithms TEXT NOT NULL,
    n_flows INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    simulator_version TEXT NOT NULL,
    config_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS presets (
    name TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    description TEXT,
    config_json TEXT NOT NULL
);
"""


def make_run_id(cfg: SimulationConfig, when: _dt.datetime | None = None) -> str:
    when = when or _dt.datetime.now()
    h = hashlib.sha1(cfg.to_json().encode()).hexdigest()[:6]
    return f"R{when.strftime('%Y%m%d-%H%M%S-%f')[:-3]}-{h}"


class ExperimentStore:
    def __init__(self, path: str | Path = DEFAULT_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con, con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    # ------------------------------------------------------------------ runs
    def save_run(self, run_id: str, cfg: SimulationConfig, metrics: dict[str, Any], label: str = "") -> None:
        with closing(self._connect()) as con, con:
            con.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, _dt.datetime.now().isoformat(timespec="seconds"), label, "+".join(cfg.algorithms),
                 cfg.n_flows, cfg.seed, cfg.to_json(), json.dumps(metrics, allow_nan=False),
                 D.SIMULATOR_VERSION, D.CONFIG_SCHEMA_VERSION),
            )

    def list_runs(self, limit: int = 500) -> pd.DataFrame:
        with closing(self._connect()) as con:
            df = pd.read_sql_query("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", con, params=(limit,))
        return df

    def runs_table(self, limit: int = 500) -> pd.DataFrame:
        """Runs with configuration and headline metrics expanded into columns."""
        df = self.list_runs(limit)
        if df.empty:
            return df
        rows = []
        for _, r in df.iterrows():
            cfg = json.loads(r["config_json"])
            m = json.loads(r["metrics_json"])
            rows.append({
                "run_id": r["run_id"], "created_at": r["created_at"], "label": r["label"],
                "algorithms": r["algorithms"], "flows": r["n_flows"], "seed": r["seed"],
                "bandwidth_mbps": cfg["bandwidth_mbps"], "delay_ms": cfg["delay_ms"],
                "buffer_packets": cfg["buffer_packets"], "loss_prob": cfg["loss_prob"],
                "duration_s": cfg["duration_s"],
                "goodput_mbps": m.get("aggregate_goodput_mbps"), "link_util_pct": m.get("link_utilisation_pct"),
                "loss_pct": m.get("loss_pct"), "avg_rtt_ms": m.get("avg_rtt_ms"),
                "timeouts": m.get("timeouts"), "fast_retransmits": m.get("fast_retransmits"),
                "jain_index": m.get("jain_index"), "simulator_version": r["simulator_version"],
            })
        return pd.DataFrame(rows)

    def get_run(self, run_id: str) -> tuple[SimulationConfig, dict[str, Any]] | None:
        with closing(self._connect()) as con:
            row = con.execute("SELECT config_json, metrics_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        return SimulationConfig.from_json(row[0]), json.loads(row[1])

    def delete_run(self, run_id: str) -> bool:
        with closing(self._connect()) as con, con:
            cur = con.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
        return cur.rowcount > 0

    def clear_runs(self) -> int:
        with closing(self._connect()) as con, con:
            cur = con.execute("DELETE FROM runs")
        return cur.rowcount

    # --------------------------------------------------------------- presets
    def save_preset(self, name: str, cfg: SimulationConfig, description: str = "") -> None:
        name = name.strip()
        if not name:
            raise ValueError("Preset name cannot be empty.")
        if len(name) > 80:
            raise ValueError("Preset name must be 80 characters or fewer.")
        cfg.ensure_valid()
        with closing(self._connect()) as con, con:
            con.execute("INSERT OR REPLACE INTO presets VALUES (?,?,?,?)",
                        (name, _dt.datetime.now().isoformat(timespec="seconds"), description, cfg.to_json()))

    def list_presets(self) -> pd.DataFrame:
        with closing(self._connect()) as con:
            return pd.read_sql_query("SELECT name, created_at, description FROM presets ORDER BY name", con)

    def load_preset(self, name: str) -> SimulationConfig:
        with closing(self._connect()) as con:
            row = con.execute("SELECT config_json FROM presets WHERE name=?", (name,)).fetchone()
        if row is None:
            raise KeyError(f"No preset named {name!r}")
        return SimulationConfig.from_json(row[0])

    def delete_preset(self, name: str) -> bool:
        with closing(self._connect()) as con, con:
            cur = con.execute("DELETE FROM presets WHERE name=?", (name,))
        return cur.rowcount > 0
