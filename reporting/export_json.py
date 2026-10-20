"""JSON export / import of experiment configurations (reproducible presets)."""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from config import defaults as D
from config.validation import ConfigValidationError, SimulationConfig


def config_document(cfg: SimulationConfig, run_id: str = "", name: str = "", description: str = "",
                    metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema": "tcp-congestion-visualizer/experiment",
        "config_version": D.CONFIG_SCHEMA_VERSION,
        "simulator_version": D.SIMULATOR_VERSION,
        "exported_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id,
        "name": name,
        "description": description,
        "config": cfg.to_dict(),
    }
    if metrics is not None:
        doc["metrics"] = metrics
    return doc


def config_json(cfg: SimulationConfig, **kwargs: Any) -> str:
    return json.dumps(config_document(cfg, **kwargs), indent=2, allow_nan=False)


def load_config_json(text: str | bytes) -> tuple[SimulationConfig, dict[str, Any]]:
    """Parse an exported document (or a bare config object). Returns (config, metadata)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigValidationError([f"File is not valid JSON: {exc}"]) from exc
    meta: dict[str, Any] = {}
    if isinstance(data, dict) and "config" in data:
        meta = {k: v for k, v in data.items() if k != "config"}
        version = data.get("config_version", D.CONFIG_SCHEMA_VERSION)
        if version > D.CONFIG_SCHEMA_VERSION:
            raise ConfigValidationError([f"Configuration version {version} is newer than this app supports "
                                         f"({D.CONFIG_SCHEMA_VERSION})."])
        data = data["config"]
    if not isinstance(data, dict):
        raise ConfigValidationError(["Configuration must be a JSON object."])
    cfg = SimulationConfig.from_dict(data)
    cfg.ensure_valid()
    return cfg, meta
