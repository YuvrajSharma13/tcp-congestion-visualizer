"""Page 7 - Learning Centre: lessons, quiz, prediction challenge."""

from __future__ import annotations

from dataclasses import replace

import streamlit as st

from config.validation import ForcedDrop, LossBurst, make_config
from learning.lessons import LESSONS
from learning.quiz import CHALLENGES, PREDICTION_METRICS, QUESTIONS
from simulator.metrics import compute_metrics
from ui import state
from ui.components import hero
from visualization import charts


def _lesson_config(spec: dict):
    kw = dict(spec)
    alg = kw.pop("algorithm")
    if "forced_drops" in kw:
        kw["forced_drops"] = tuple(ForcedDrop(f, s) for f, s in kw["forced_drops"])
    if "loss_bursts" in kw:
        kw["loss_bursts"] = tuple(LossBurst(a, b) for a, b in kw["loss_bursts"])
    return make_config(alg, **kw)


def render() -> None:
    hero("Learn", "Learning Centre",
         "Short lessons tied to the simulator, a quiz, and a prediction challenge that checks your intuition "
         "against a real run.")
    t1, t2, t3 = st.tabs(["Lessons", "Quiz", "Prediction challenge"])
    with t1:
        _lessons()
    with t2:
        _quiz()
    with t3:
        _challenge()


def _lessons() -> None:
    titles = [f"{i + 1}. {l['title']}" for i, l in enumerate(LESSONS)]
    i = st.radio("Lesson", range(len(LESSONS)), format_func=lambda k: titles[k], horizontal=True,
                 key="learn_lesson", label_visibility="collapsed")
    lesson = LESSONS[i]
    st.markdown(f"### {lesson['title']}")
    st.markdown(lesson["body"])
    if lesson["try"]:
        cfg = _lesson_config(lesson["try"])
        if st.button("Try it: run a small simulation that shows this", key=f"try_{lesson['id']}", type="primary"):
            res = state.simulate(cfg)
            state.record_run(cfg, res, f"lesson: {lesson['title']}", "learning")
            st.session_state[f"lesson_res_{lesson['id']}"] = res
        res = st.session_state.get(f"lesson_res_{lesson['id']}")
        if res is not None:
            fig, note = charts.cwnd_chart(res, height=330)
            st.plotly_chart(fig, width="stretch", key=f"lesson_fig_{lesson['id']}")
            if note:
                st.caption(note)
            m = compute_metrics(res)
            st.caption(f"Goodput {m.aggregate_goodput_mbps:.2f} Mbps · {m.fast_retransmits} fast retransmits · "
                       f"{m.timeouts} timeouts · {m.drops_by_type['overflow']} overflow drops")
    c1, c2 = st.columns(2)
    if i > 0 and c1.button("← Previous lesson"):
        st.session_state.learn_lesson = i - 1
        st.rerun()
    if i < len(LESSONS) - 1 and c2.button("Next lesson →"):
        st.session_state.learn_lesson = i + 1
        st.rerun()


def _quiz() -> None:
    ss = st.session_state
    ss.setdefault("quiz_answers", {})
    answers = ss.quiz_answers
    score = sum(1 for k, v in answers.items() if v == QUESTIONS[k].answer)
    st.markdown(f"**Score: {score} / {len(answers)} answered** ({len(QUESTIONS)} questions)")
    st.progress(len(answers) / len(QUESTIONS))
    for qi, q in enumerate(QUESTIONS):
        with st.container(border=True):
            st.markdown(f"**Q{qi + 1}. {q.prompt}**")
            done = qi in answers
            choice = st.radio("Answer", range(len(q.options)), format_func=lambda k, q=q: q.options[k],
                              key=f"quiz_{qi}_{ss.get('quiz_round', 0)}", index=None, disabled=done,
                              label_visibility="collapsed")
            if not done:
                if st.button("Check", key=f"quiz_check_{qi}_{ss.get('quiz_round', 0)}", disabled=choice is None):
                    answers[qi] = choice
                    st.rerun()
            else:
                ok = answers[qi] == q.answer
                (st.success if ok else st.error)(("Correct. " if ok else f"Not quite - the answer is "
                                                  f"'{q.options[q.answer]}'. ") + q.explanation)
    if answers and len(answers) == len(QUESTIONS):
        st.balloons() if score == len(QUESTIONS) else None
        st.markdown(f"### Final score: {score}/{len(QUESTIONS)}")
    if st.button("Restart quiz"):
        ss.quiz_answers = {}
        ss.quiz_round = ss.get("quiz_round", 0) + 1
        st.rerun()


def _challenge() -> None:
    st.markdown("Pick a change to the baseline network (TCP Reno, 10 Mbps, 20 ms one-way, 35-packet buffer, 30 s). "
                "Predict how each metric moves, then run both networks and compare.")
    ch = st.selectbox("Change", CHALLENGES, format_func=lambda c: f"{c.title} ({c.change})", key="chal_pick")
    preds = {}
    cols = st.columns(len(PREDICTION_METRICS))
    for c, (k, lab) in zip(cols, PREDICTION_METRICS.items()):
        preds[k] = c.radio(lab, ["increase", "stay about the same", "decrease"], key=f"chal_{ch.id}_{k}", index=None)
    base = make_config(ch.algorithm, duration_s=30, bandwidth_mbps=10, delay_ms=20, buffer_packets=35)
    base = replace(base, **{ch.param: type(getattr(base, ch.param))(ch.base_value)})
    changed = replace(base, **{ch.param: type(getattr(base, ch.param))(ch.new_value)})
    if st.button("Run both and reveal", type="primary", disabled=any(v is None for v in preds.values())):
        a, b = state.simulate(base), state.simulate(changed)
        state.record_run(base, a, f"challenge baseline: {ch.title}", "learning")
        state.record_run(changed, b, f"challenge changed: {ch.title}", "learning")
        st.session_state.chal_result = (ch.id, compute_metrics(a), compute_metrics(b), a, b, dict(preds))
    r = st.session_state.get("chal_result")
    if not r or r[0] != ch.id:
        return
    _, ma, mb, a, b, preds = r
    right = 0
    for k, lab in PREDICTION_METRICS.items():
        va, vb = getattr(ma, k if k != "goodput_mbps" else "aggregate_goodput_mbps"), \
            getattr(mb, k if k != "goodput_mbps" else "aggregate_goodput_mbps")
        rel = (vb - va) / va if va else (0.0 if vb == 0 else 1.0)
        actual = "increase" if rel > 0.05 else "decrease" if rel < -0.05 else "stay about the same"
        ok = actual == preds[k]
        right += ok
        (st.success if ok else st.warning)(f"**{lab}**: {va:.2f} → {vb:.2f} ({rel * 100:+.0f}%), it "
                                           f"{'stayed about the same' if actual.startswith('stay') else actual + 'd'}. "
                                           f"You predicted '{preds[k]}'.")
    st.markdown(f"**{right}/{len(PREDICTION_METRICS)} predictions correct.** (A change within ±5% counts as "
                f"'about the same'.)")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("Baseline")
        st.plotly_chart(charts.cwnd_chart(a, height=300)[0], width="stretch", key="chal_a")
    with c2:
        st.markdown(f"Changed: {ch.change}")
        st.plotly_chart(charts.cwnd_chart(b, height=300)[0], width="stretch", key="chal_b")
