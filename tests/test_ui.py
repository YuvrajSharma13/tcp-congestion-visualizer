"""Dashboard smoke and interaction tests using Streamlit's headless AppTest runner."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["overview", "simulation_lab", "playback", "comparison", "scenarios", "sensitivity", "experiments",
         "learning", "ml_lab", "validation_page"]


def page(name: str) -> AppTest:
    code = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom ui.views import {name}\n{name}.render()\n"
    return AppTest.from_string(code, default_timeout=180)


def ok(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]


def button(at: AppTest, label: str):
    matches = [b for b in at.button if b.label == label]
    assert matches, f"no button {label!r}; have {[b.label for b in at.button]}"
    return matches[0]


def test_app_entry_point_loads():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.run()
    ok(at)


@pytest.mark.parametrize("name", PAGES)
def test_every_page_renders_without_a_run(name):
    at = page(name)
    at.run()
    ok(at)


def test_overview_shows_no_fabricated_statistics_before_a_run():
    at = page("overview")
    at.run()
    assert any("No simulation has been run" in i.value for i in at.info)


def test_lab_run_then_replay_reproduces():
    at = page("simulation_lab")
    at.run()
    button(at, "Run simulation").click().run()
    ok(at)
    assert len(at.tabs) == 7
    button(at, "Replay last run").click().run()
    ok(at)
    assert any("identical" in s.value for s in at.success)


def test_lab_shows_validation_errors_for_invalid_input():
    at = page("simulation_lab")
    at.run()
    at.number_input(key="lab_bw").set_value(0.01).run()
    at.number_input(key="lab_dur").set_value(300.0).run()
    at.number_input(key="lab_bw").set_value(1000.0).run()
    ok(at)
    assert any("cannot be simulated" in e.value for e in at.error)


def test_comparison_page_runs_all_algorithms():
    at = page("comparison")
    at.run()
    at.number_input(key="cmp_dur").set_value(5.0).run()
    button(at, "Run comparison").click().run()
    ok(at)
    assert len(at.session_state["cmp_runs"]) == 4


def test_scenario_page_runs_and_reports_checks():
    at = page("scenarios")
    at.run()
    at.radio(key="sc_idx").set_value(3).run()   # burst -> timeout
    button(at, "Run scenario").click().run()
    ok(at)
    assert at.session_state["sc_last"][0] == "burst_timeout"


def test_packet_playback_demo_steps_forward_and_back():
    at = page("playback")
    at.run()
    button(at, "Load demo trace").click().run()
    ok(at)
    button(at, "Step ▶").click().run()
    button(at, "Step ▶").click().run()
    assert at.session_state["pb_idx"] == 2
    button(at, "◀ Step").click().run()
    assert at.session_state["pb_idx"] == 1
    at.selectbox(key="pb_focus").set_value("first fast retransmit").run()
    ok(at)


def test_learning_quiz_scores_answers():
    at = page("learning")
    at.run()
    at.radio(key="quiz_0_0").set_value(1).run()
    [b for b in at.button if b.key == "quiz_check_0_0"][0].click().run()
    ok(at)
    assert at.session_state["quiz_answers"] == {0: 1}


def test_ml_page_predicts_on_a_run_when_model_present():
    if not (ROOT / "models" / "congestion_model.joblib").exists():
        pytest.skip("no trained model bundled")
    at = page("overview")
    at.run()
    button(at, "Run the current configuration now").click().run()
    ok(at)
    hist = at.session_state["history"]
    at2 = page("ml_lab")
    at2.session_state["history"] = hist
    at2.run()
    ok(at2)
    assert not any("No trained model" in i.value for i in at2.info)


def test_experiments_page_exports_after_a_run():
    at = page("overview")
    at.run()
    button(at, "Run the current configuration now").click().run()
    at2 = page("experiments")
    at2.session_state["history"] = at.session_state["history"]
    at2.run()
    ok(at2)
    button(at2, "Build HTML report").click().run()
    ok(at2)
    assert at2.session_state["exp_report"][1].startswith("<!doctype html>")
