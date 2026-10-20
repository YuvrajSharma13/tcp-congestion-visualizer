"""Apply a trained congestion model to a finished simulation (read-only).

The model only *reads* the recorded telemetry of a completed run.  It has no
access to the simulator while it runs and cannot change cwnd or any other
algorithm state - it is an analysis and learning tool, not a TCP controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ml.dataset import FEATURE_LABELS, FEATURES, features_from_series, labels_from_series, link_series
from ml.train import MODEL_PATH
from simulator.trace import SimulationResult

RISK_BANDS = ((0.3, "low"), (0.6, "medium"), (1.01, "high"))


@dataclass
class ModelStatus:
    ok: bool
    message: str
    bundle: dict | None = None


def risk_level(p: float) -> str:
    for edge, name in RISK_BANDS:
        if p < edge:
            return name
    return "high"


def load_model(path: Path = MODEL_PATH) -> ModelStatus:
    if not Path(path).exists():
        return ModelStatus(False, "No trained model found. Train one on this page or run `python -m ml.train`.")
    try:
        import joblib
        import sklearn

        bundle = joblib.load(path)
    except Exception as exc:  # corrupted file or incompatible library version
        return ModelStatus(False, f"The saved model could not be loaded ({type(exc).__name__}: {exc}). "
                                  f"Retrain it on this page.")
    if bundle.get("features") != FEATURES:
        return ModelStatus(False, "The saved model uses a different feature set; retrain it.")
    msg = "Model loaded."
    if bundle.get("sklearn_version") != sklearn.__version__:
        msg = (f"Model was trained with scikit-learn {bundle.get('sklearn_version')}, this environment has "
               f"{sklearn.__version__}; retrain if predictions look wrong.")
    return ModelStatus(True, msg, bundle)


def predict_run(bundle: dict, result: SimulationResult) -> pd.DataFrame:
    """Probability of an overflow within the horizon at every sample time with a complete window."""
    series = link_series(result)
    if series.empty:
        return pd.DataFrame(columns=["t", "prob", "risk", "actual"] + FEATURES)
    feats = features_from_series(series, result.config, bundle["window_s"])
    feats = feats[feats["_complete"]].drop(columns="_complete")
    if feats.empty:
        return pd.DataFrame(columns=["t", "prob", "risk", "actual"] + FEATURES)
    prob = bundle["model"].predict_proba(feats[FEATURES].to_numpy(float))[:, 1]
    labels = labels_from_series(series, bundle["horizon_s"])
    out = feats.copy()
    out["prob"] = prob
    out["risk"] = [risk_level(p) for p in prob]
    out = out.merge(labels.rename(columns={"label": "actual"}), on="t", how="left")
    return out.reset_index(drop=True)


def explain_prediction(bundle: dict, row: pd.Series, top: int = 4) -> pd.DataFrame:
    """Logistic-regression contributions (coefficient x standardised value) for one prediction.

    Uses the logistic-regression model trained on the same data even when the
    deployed model is the random forest, as a transparent local explanation.
    """
    x = np.array([float(row[f]) for f in FEATURES])
    mean = np.array(bundle["lr_scaler_mean"])
    scale = np.array(bundle["lr_scaler_scale"])
    coef = np.array([bundle["lr_coefficients"][f] for f in FEATURES])
    z = (x - mean) / np.where(scale > 0, scale, 1)
    contrib = coef * z
    df = pd.DataFrame({"feature": FEATURES, "label": [FEATURE_LABELS[f] for f in FEATURES], "value": x,
                       "z": z, "contribution": contrib})
    return df.reindex(df["contribution"].abs().sort_values(ascending=False).index).head(top).reset_index(drop=True)


def explanation_text(contrib: pd.DataFrame) -> str:
    parts = []
    for _, r in contrib.iterrows():
        direction = "raises" if r["contribution"] > 0 else "lowers"
        level = "high" if r["z"] > 0.5 else "low" if r["z"] < -0.5 else "typical"
        parts.append(f"{r['label']} is {level} ({r['value']:.3g}), which {direction} the risk")
    return "; ".join(parts) + "." if parts else "No dominant signal."
