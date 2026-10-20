"""Train and evaluate the congestion classifier.

Protocol
--------
1. Hold out 25% of *network configurations* (all seeds of a configuration go
   to the same side) with ``GroupShuffleSplit`` on ``config_id``.
2. On the training side, choose between Logistic Regression and a calibrated
   Random Forest by grouped 4-fold cross-validated ROC-AUC, and pick the
   decision threshold that maximises cross-validated F1.  The test set is not
   used for any choice.
3. Report the chosen model and two baselines on the held-out configurations:
   a majority-class predictor and a single-feature rule (queue occupancy above
   a threshold tuned on the training data).

Run from the project folder:  ``python -m ml.train``
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from config import defaults as D
from ml.dataset import DEFAULT_HORIZON_S, DEFAULT_STRIDE_S, DEFAULT_WINDOW_S, FEATURES, generate_dataset
from ml.evaluate import best_f1_threshold, calibration_table, classification_metrics

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_PATH = MODEL_DIR / "congestion_model.joblib"
MIN_ROWS = 300
MIN_GROUPS = 6


class InsufficientDataError(ValueError):
    pass


def check_data(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        raise InsufficientDataError("No training rows: generate a dataset first.")
    if len(df) < MIN_ROWS:
        raise InsufficientDataError(f"Only {len(df)} rows; at least {MIN_ROWS} are needed.")
    groups = df["config_id"].nunique()
    if groups < MIN_GROUPS:
        raise InsufficientDataError(f"Only {groups} network configurations; at least {MIN_GROUPS} are needed "
                                    f"so that evaluation can hold out whole configurations.")
    if df["label"].nunique() < 2:
        raise InsufficientDataError("All rows have the same label; vary the configurations (buffer, loss, flows).")


def group_split(df: pd.DataFrame, test_size: float = 0.25, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    tr, te = next(gss.split(df, df["label"], groups=df["config_id"]))
    return tr, te


def _make(kind: str, groups_cv=None):
    if kind == "logistic_regression":
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
    if kind == "random_forest":
        rf = RandomForestClassifier(n_estimators=200, max_depth=8, min_samples_leaf=20, n_jobs=-1, random_state=0)
        return CalibratedClassifierCV(rf, method="isotonic", cv=groups_cv or 3)
    raise ValueError(kind)


def _cv_predict(kind: str, X: np.ndarray, y: np.ndarray, groups: np.ndarray, n_splits: int = 4) -> np.ndarray:
    prob = np.zeros(len(y))
    for tr, va in GroupKFold(n_splits=n_splits).split(X, y, groups):
        if len(np.unique(y[tr])) < 2:
            prob[va] = y[tr].mean()
            continue
        inner = list(GroupKFold(n_splits=3).split(X[tr], y[tr], groups[tr])) if kind == "random_forest" else None
        m = _make(kind, inner)
        m.fit(X[tr], y[tr])
        prob[va] = m.predict_proba(X[va])[:, 1]
    return prob


def train(df: pd.DataFrame, seed: int = 0, progress=None) -> dict:
    check_data(df)
    df = df.reset_index(drop=True)
    tr, te = group_split(df, seed=seed)
    train_df, test_df = df.iloc[tr], df.iloc[te]
    if train_df["label"].nunique() < 2 or test_df["label"].nunique() < 2:
        raise InsufficientDataError("The configuration-level split left one side with a single class; "
                                    "generate more configurations.")
    X, y, g = train_df[FEATURES].to_numpy(float), train_df["label"].to_numpy(int), train_df["config_id"].to_numpy()
    Xt, yt = test_df[FEATURES].to_numpy(float), test_df["label"].to_numpy(int)
    n_splits = min(4, train_df["config_id"].nunique())

    cv = {}
    for i, kind in enumerate(("logistic_regression", "random_forest")):
        if progress:
            progress(f"cross-validating {kind.replace('_', ' ')}", i / 3)
        p = _cv_predict(kind, X, y, g, n_splits)
        thr = best_f1_threshold(y, p)
        cv[kind] = {"cv_roc_auc": classification_metrics(y, p, thr)["roc_auc"], "threshold": thr,
                    "cv_f1": classification_metrics(y, p, thr)["f1"]}
    chosen = max(cv, key=lambda k: (cv[k]["cv_roc_auc"] if not math.isnan(cv[k]["cv_roc_auc"]) else -1))
    if progress:
        progress("fitting final models", 2 / 3)

    models = {}
    for kind in cv:
        inner = list(GroupKFold(n_splits=min(3, n_splits)).split(X, y, g)) if kind == "random_forest" else None
        m = _make(kind, inner)
        m.fit(X, y)
        models[kind] = m

    evaluation = {}
    test_probs = {}
    for kind, m in models.items():
        p = m.predict_proba(Xt)[:, 1]
        test_probs[kind] = p
        evaluation[kind] = classification_metrics(yt, p, cv[kind]["threshold"])

    # baselines
    maj = float(y.mean() >= 0.5)
    evaluation["baseline_majority"] = classification_metrics(yt, np.full(len(yt), maj), 0.5)
    qi = FEATURES.index("queue_frac")
    grid = np.linspace(0.05, 1.0, 20)
    q_thr = float(grid[int(np.argmax([classification_metrics(y, (X[:, qi] >= th).astype(float), 0.5)["f1"]
                                      for th in grid]))])
    evaluation["baseline_queue_rule"] = classification_metrics(yt, (Xt[:, qi] >= q_thr).astype(float), 0.5)
    evaluation["baseline_queue_rule"]["rule"] = f"queue_frac >= {q_thr:.2f}"

    # interpretability
    lr = models["logistic_regression"]
    coefs = dict(zip(FEATURES, lr.named_steps["logisticregression"].coef_[0].tolist()))
    pi = permutation_importance(models[chosen], Xt, yt, scoring="roc_auc", n_repeats=5, random_state=0)
    importance = dict(zip(FEATURES, pi.importances_mean.tolist()))

    if progress:
        progress("done", 1.0)
    return {
        "model": models[chosen],
        "models": models,
        "chosen": chosen,
        "threshold": cv[chosen]["threshold"],
        "features": list(FEATURES),
        "cv": cv,
        "evaluation": evaluation,
        "calibration": calibration_table(yt, test_probs[chosen]).to_dict("records"),
        "lr_coefficients": coefs,
        "lr_scaler_mean": lr.named_steps["standardscaler"].mean_.tolist(),
        "lr_scaler_scale": lr.named_steps["standardscaler"].scale_.tolist(),
        "permutation_importance": importance,
        "train_summary": {
            "rows": int(len(df)), "train_rows": int(len(train_df)), "test_rows": int(len(test_df)),
            "configs": int(df["config_id"].nunique()), "train_configs": sorted(train_df["config_id"].unique()),
            "test_configs": sorted(test_df["config_id"].unique()), "runs": int(df["run_id"].nunique()),
            "positive_rate": float(df["label"].mean()),
        },
        "window_s": float(df.attrs.get("window_s", DEFAULT_WINDOW_S)),
        "horizon_s": float(df.attrs.get("horizon_s", DEFAULT_HORIZON_S)),
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "simulator_version": D.SIMULATOR_VERSION,
    }


def save_model(bundle: dict, path: Path = MODEL_PATH) -> Path:
    import joblib

    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    summary = {k: v for k, v in bundle.items() if k not in ("model", "models")}
    path.with_suffix(".json").write_text(json.dumps(summary, indent=2, default=float))
    return path


def build_and_train(n_configs: int = 48, seeds=(1, 2), duration_s: float = 15.0, rng_seed: int = 0,
                    progress=None) -> tuple[pd.DataFrame, dict]:
    df = generate_dataset(n_configs, tuple(seeds), duration_s, rng_seed,
                          progress=(lambda i, n: progress(f"simulating run {i}/{n}", 0.6 * i / n)) if progress else None)
    df.attrs.update(window_s=DEFAULT_WINDOW_S, horizon_s=DEFAULT_HORIZON_S, stride_s=DEFAULT_STRIDE_S)
    bundle = train(df, progress=(lambda msg, f: progress(msg, 0.6 + 0.4 * f)) if progress else None)
    return df, bundle


def _fmt_eval(ev: dict) -> str:
    lines = [f"{'model':28s} {'prec':>6s} {'recall':>6s} {'F1':>6s} {'ROC-AUC':>8s} {'Brier':>6s}"]
    for k, m in ev.items():
        lines.append(f"{k:28s} {m['precision']:6.3f} {m['recall']:6.3f} {m['f1']:6.3f} "
                     f"{m['roc_auc']:8.3f} {m['brier']:6.3f}")
    return "\n".join(lines)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Generate simulated telemetry, train and evaluate the congestion model.")
    ap.add_argument("--configs", type=int, default=48, help="number of random network configurations")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    ap.add_argument("--duration", type=float, default=15.0)
    ap.add_argument("--rng-seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=MODEL_PATH)
    a = ap.parse_args(argv)
    df, bundle = build_and_train(a.configs, a.seeds, a.duration, a.rng_seed,
                                 progress=lambda msg, f: print(f"[{f * 100:5.1f}%] {msg}", flush=True))
    path = save_model(bundle, a.out)
    s = bundle["train_summary"]
    print(f"\n{s['rows']} rows from {s['runs']} runs / {s['configs']} configurations "
          f"(test = {len(s['test_configs'])} held-out configurations), positive rate {s['positive_rate']:.2f}")
    print(f"chosen model: {bundle['chosen']} (grouped CV ROC-AUC {bundle['cv'][bundle['chosen']]['cv_roc_auc']:.3f}),"
          f" threshold {bundle['threshold']:.2f}\n")
    print(_fmt_eval(bundle["evaluation"]))
    print(f"\nsaved to {path}")


if __name__ == "__main__":
    main()
