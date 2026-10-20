"""FastAPI backend: every endpoint, validation errors, payload shape."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json()["status"] == "ok"


def test_simulate_returns_kpis_series_events_and_playback():
    r = client.post("/api/simulate", json={"algorithm": "newreno", "duration_s": 6, "buffer_packets": 10})
    assert r.status_code == 200
    d = r.json()
    k = d["kpis"]
    assert 0 < k["goodput_mbps"] <= k["capacity_mbps"] and 0 <= k["link_utilisation_pct"] <= 100
    assert k["packets_dropped"] == sum(k["drops_by_cause"].values())
    assert d["cwnd"][0]["points"] and d["queue"] and d["rtt"]
    assert all(e["explanation"] for e in d["events"])
    pb = d["playback"]
    assert pb and pb["packets"] and pb["acks"]
    # timestamps in each packet row are causal: send <= tx start <= tx end <= receive
    for row in pb["packets"][:500]:
        ts, tenq, tx0, tx1, trx = row[4:9]
        if trx is not None:
            assert ts <= tx0 <= tx1 <= trx


def test_simulate_is_reproducible():
    body = {"algorithm": "cubic", "duration_s": 5, "loss_rate": 1, "seed": 9, "playback": False}
    a, b = client.post("/api/simulate", json=body).json(), client.post("/api/simulate", json=body).json()
    assert a["kpis"] == b["kpis"] and a["cwnd"] == b["cwnd"]


def test_invalid_configuration_is_422_with_messages():
    r = client.post("/api/simulate", json={"bandwidth_mbps": 1000, "duration_s": 300})
    assert r.status_code == 422 and "packets" in r.json()["detail"]["errors"][0]
    assert client.post("/api/simulate", json={"algorithm": "vegas"}).status_code == 422


def test_compare_uses_identical_conditions():
    d = client.post("/api/compare", json={"duration_s": 5, "loss_rate": 0.5}).json()
    assert [r["algorithm"] for r in d["rows"]] == ["tahoe", "reno", "newreno", "cubic"]
    assert len(d["cwnd"]) == 4 and d["notes"]
    assert all(r["jain_index"] is None for r in d["rows"])  # single flow


def test_scenarios_list_and_run():
    lst = client.get("/api/scenarios").json()
    assert len(lst) == 9 and {"multi_loss", "high_bdp"} <= {s["id"] for s in lst}
    r = client.post("/api/scenarios/multi_loss/run", json={"algorithm": "reno"}).json()
    assert r["checks"][0]["status"] == "consistent"
    assert client.post("/api/scenarios/unknown/run").status_code == 404


def test_predict_and_validation():
    d = client.post("/api/predict", json={"duration_s": 8, "buffer_packets": 15}).json()
    if d["available"]:
        assert d["points"] and 0 <= d["peak"]["prob"] <= 1 and d["contributions"]
    else:
        assert "model" in d["message"].lower()
    v = client.get("/api/validation").json()
    assert v["failed"] == 0 and v["passed"] > 30
