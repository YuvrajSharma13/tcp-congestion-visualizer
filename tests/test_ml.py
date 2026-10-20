"""Congestion-prediction module: leakage, grouped splits, insufficient data, metrics."""

import math

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

from config.validation import make_config
from ml.dataset import FEATURES, features_from_series, labels_from_series, link_series, rows_for_run, sample_configs
from ml.evaluate import calibration_table, classification_metrics, confusion
from ml.predict import load_model, predict_run, risk_level
from ml.train import InsufficientDataError, check_data, group_split, train
from simulator.engine import run_simulation


@pytest.fixture(scope="module")
def res():
    return run_simulation(make_config(["reno", "cubic"], n_flows=2, duration_s=6, buffer_packets=10,
                                      loss_prob=0.005, record_packet_events=False))


def test_features_use_only_past_information(res):
    series = link_series(res)
    full = features_from_series(series, res.config).set_index("t")
    for cut in (1.0, 2.5, 4.0):
        trunc = features_from_series(series[series["t"] <= cut + 1e-9], res.config).set_index("t")
        a = full.loc[trunc.index[-1], FEATURES].astype(float)
        b = trunc.iloc[-1][FEATURES].astype(float)
        pd.testing.assert_series_equal(a, b, check_names=False)


def test_future_changes_do_not_alter_features_but_do_alter_labels(res):
    series = link_series(res)
    i = len(series) // 2
    tampered = series.copy()
    tampered.loc[i + 1:, "overflow_total"] += 1000
    tampered.loc[i + 1:, "queue"] = 0
    f0 = features_from_series(series, res.config).iloc[i][FEATURES].astype(float)
    f1 = features_from_series(tampered, res.config).iloc[i][FEATURES].astype(float)
    pd.testing.assert_series_equal(f0, f1)
    assert labels_from_series(tampered).iloc[i]["label"] == 1.0


def test_labels_refer_to_the_horizon_only(res):
    series = link_series(res)
    lab = labels_from_series(series, horizon_s=0.2)
    ov = series["overflow_total"].to_numpy()
    h = 20  # 0.2 s / 10 ms samples
    for i in range(0, len(series) - h, 37):
        assert lab["label"].iloc[i] == float(ov[i + h] > ov[i])
    assert lab["label"].iloc[-h:].isna().all()


def _toy_rows(n_groups=12, per=60, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_groups):
        X = rng.normal(size=(per, len(FEATURES)))
        y = (X[:, 0] + 0.3 * rng.normal(size=per) > 0).astype(float)
        df = pd.DataFrame(X, columns=FEATURES)
        df["label"] = y
        df["config_id"] = f"C{g}"
        df["run_id"] = [f"C{g}-s{k % 2}" for k in range(per)]
        df["t"] = np.arange(per) * 0.05
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


def test_group_split_keeps_configurations_on_one_side():
    df = _toy_rows()
    tr, te = group_split(df)
    a, b = set(df.iloc[tr]["config_id"]), set(df.iloc[te]["config_id"])
    assert a and b and a.isdisjoint(b)
    ra, rb = set(df.iloc[tr]["run_id"]), set(df.iloc[te]["run_id"])
    assert ra.isdisjoint(rb)


def test_training_records_disjoint_configs_and_beats_majority_on_toy_data():
    bundle = train(_toy_rows())
    s = bundle["train_summary"]
    assert set(s["train_configs"]).isdisjoint(s["test_configs"])
    ev = bundle["evaluation"]
    assert ev[bundle["chosen"]]["roc_auc"] > 0.8
    assert ev[bundle["chosen"]]["f1"] > ev["baseline_majority"]["f1"]


def test_insufficient_data_is_reported():
    with pytest.raises(InsufficientDataError):
        check_data(pd.DataFrame())
    small = _toy_rows(n_groups=3, per=20)
    with pytest.raises(InsufficientDataError):
        train(small)
    one_class = _toy_rows()
    one_class["label"] = 0.0
    with pytest.raises(InsufficientDataError, match="same label"):
        check_data(one_class)


def test_missing_model_gives_clear_message(tmp_path):
    st = load_model(tmp_path / "none.joblib")
    assert not st.ok and "No trained model" in st.message
    bad = tmp_path / "bad.joblib"
    bad.write_bytes(b"not a model")
    st = load_model(bad)
    assert not st.ok and "could not be loaded" in st.message


def test_metrics_match_sklearn():
    rng = np.random.default_rng(3)
    y = rng.integers(0, 2, 300)
    p = np.clip(y * 0.4 + rng.uniform(0, 0.6, 300), 0, 1)
    m = classification_metrics(y, p, 0.5)
    pred = (p >= 0.5).astype(int)
    assert m["precision"] == pytest.approx(precision_score(y, pred))
    assert m["recall"] == pytest.approx(recall_score(y, pred))
    assert m["f1"] == pytest.approx(f1_score(y, pred))
    assert m["roc_auc"] == pytest.approx(roc_auc_score(y, p))
    c = confusion(y, pred)
    assert c["tp"] + c["fp"] + c["tn"] + c["fn"] == 300
    assert math.isnan(classification_metrics(np.ones(5), np.ones(5) * 0.7, 0.5)["roc_auc"])
    assert classification_metrics(np.zeros(4), np.zeros(4), 0.5)["precision"] == 0.0
    cal = calibration_table(y, p)
    assert cal["count"].sum() == 300


def test_rows_for_run_and_prediction_do_not_touch_simulation(res):
    rows = rows_for_run(res, "r", "c")
    assert set(FEATURES) <= set(rows.columns) and rows["label"].isin([0, 1]).all()
    assert rows["t"].min() >= max(f.start_time_s for f in res.config.flows) + 0.2 - 1e-9
    before = res.cwnd.copy()
    bundle = train(_toy_rows())
    bundle.update(window_s=0.2, horizon_s=0.2)
    pred = predict_run(bundle, res)
    assert pred["prob"].between(0, 1).all()
    assert set(pred["risk"]) <= {"low", "medium", "high"}
    pd.testing.assert_frame_equal(before, res.cwnd)   # predictions are read-only
    assert risk_level(0.1) == "low" and risk_level(0.45) == "medium" and risk_level(0.9) == "high"


def test_sample_configs_are_valid_and_diverse():
    cfgs = sample_configs(20, rng_seed=1, duration_s=5)
    assert len({c.to_json() for _, c in cfgs}) == 20
    assert all(c.validate() == [] for _, c in cfgs)
