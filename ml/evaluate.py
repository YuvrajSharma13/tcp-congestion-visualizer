"""Evaluation metrics for the congestion classifier (computed explicitly, then cross-checked in tests)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def confusion(y: np.ndarray, pred: np.ndarray) -> dict[str, int]:
    y = np.asarray(y).astype(int)
    pred = np.asarray(pred).astype(int)
    return {"tp": int(((y == 1) & (pred == 1)).sum()), "fp": int(((y == 0) & (pred == 1)).sum()),
            "tn": int(((y == 0) & (pred == 0)).sum()), "fn": int(((y == 1) & (pred == 0)).sum())}


def classification_metrics(y: np.ndarray, prob: np.ndarray, threshold: float) -> dict[str, float]:
    y = np.asarray(y).astype(int)
    prob = np.asarray(prob, dtype=float)
    pred = (prob >= threshold).astype(int)
    c = confusion(y, pred)
    precision = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else 0.0
    recall = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    both = len(np.unique(y)) == 2
    return {
        "n": int(len(y)), "positive_rate": float(y.mean()) if len(y) else math.nan,
        "threshold": float(threshold),
        "accuracy": float((pred == y).mean()) if len(y) else math.nan,
        "precision": precision, "recall": recall, "f1": f1,
        "roc_auc": float(roc_auc_score(y, prob)) if both else math.nan,
        "pr_auc": float(average_precision_score(y, prob)) if both else math.nan,
        "brier": float(brier_score_loss(y, np.clip(prob, 0, 1))) if len(y) else math.nan,
        **c,
    }


def best_f1_threshold(y: np.ndarray, prob: np.ndarray) -> float:
    grid = np.linspace(0.05, 0.95, 91)
    scores = [classification_metrics(y, prob, th)["f1"] for th in grid]
    return float(grid[int(np.argmax(scores))])


def calibration_table(y: np.ndarray, prob: np.ndarray, bins: int = 10) -> pd.DataFrame:
    y = np.asarray(y).astype(int)
    prob = np.asarray(prob, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(prob, edges[1:-1]), 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        if m.sum() == 0:
            continue
        rows.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "mean_predicted": float(prob[m].mean()),
                     "observed_rate": float(y[m].mean()), "count": int(m.sum())})
    return pd.DataFrame(rows)
