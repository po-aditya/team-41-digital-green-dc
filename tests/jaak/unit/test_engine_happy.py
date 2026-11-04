"""Unit tests for the JaakEngine happy path (task 7.2).
Covers Req 2.1, 5.8, 5.9, 14.1, 14.5, 15.2, 20.3, 20.7.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mel_agent.data import validator
from mel_agent.jaak.engine import JaakEngine
from mel_agent.jaak.errors import NotEnded, SessionFinalised, TurnsPending, UnknownSession
from mel_agent.jaak.models import AnswerReceipt, ResponseRecord, Timeout, Turn

ROOT = Path(__file__).resolve().parents[3]
SCEN = ROOT / "data" / "participant-pack" / "json" / "scenarios"
SCENARIOS = sorted(p.name for p in SCEN.iterdir() if (p / "survey.en-IN.json").exists())
LANGS = ("en-IN", "hi-IN")
NOW = datetime(2026, 12, 7, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
GREETING_REPLY = "ok"
OPERATIONS = {"start_session", "next_turn", "submit_answer", "submit_event", "get_response"}


def load(scenario: str, lang: str) -> dict:
    return json.loads((SCEN / scenario / f"survey.{lang}.json").read_text(encoding="utf-8"))


def make_engine() -> JaakEngine:
    return JaakEngine(clock=lambda: NOW)


def start(engine: JaakEngine, scenario: str, lang: str):
    survey = load(scenario, lang)
    farmer = {"farmer_id": survey["farmer_id"], "language": lang}
    return survey, engine.start_session(survey, farmer)


def good_answer(item: dict) -> str:
    if item["type"] == "survey-scale":
        return str(item["scale_min"] if "scale_min" in item else 1)
    return item["options"][0]["label"]


def play(engine: JaakEngine, sid: str, survey: dict) -> list[Turn]:
    """Drain Turns, answering each reply-expecting Turn with a valid reply."""
    items = {i["item_id"]: i for i in survey["items"]}
    turns: list[Turn] = []
    while True:
        turn = engine.next_turn(sid)
        if turn is None:
            return turns
        turns.append(turn)
        if turn.kind == "greeting":
            reply = GREETING_REPLY
        elif turn.kind == "question":
            reply = good_answer(items[turn.item_id])
        else:
            assert turn.kind == "closing", turn.kind
            continue
        assert turn.expects_reply
        assert engine.submit_answer(sid, reply, utterance_complete=True) is AnswerReceipt.PROCESSED


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_full_run(scenario, lang):
    assert len(SCENARIOS) == 5
    engine = make_engine()
    survey, sid = start(engine, scenario, lang)
    turns = play(engine, sid, survey)

    kinds = [t.kind for t in turns]
    n = len(survey["items"])
    assert kinds == ["greeting"] + ["question"] * n + ["closing"]
    assert [t.item_id for t in turns[1:-1]] == [i["item_id"] for i in survey["items"]]
    assert all(t.language == survey["language"] == lang for t in turns)
    assert turns[-1].expects_reply is False

    # No Turn after the closing Turn is taken.
    assert engine.next_turn(sid) is None

    rec = engine.get_response(sid)
    assert list(validator("response").iter_errors(rec)) == []
    ResponseRecord.model_validate(rec)
    assert rec["channel"] == "voice"
    assert rec["language"] == survey["language"]
    assert rec["survey_id"] == survey["survey_id"]
    assert rec["farmer_id"] == survey["farmer_id"]
    assert len(rec["items"]) == n


def test_get_response_repeat_returns_cached_record():
    engine = make_engine()
    survey, sid = start(engine, SCENARIOS[0], "en-IN")
    play(engine, sid, survey)
    first = engine.get_response(sid)
    assert engine.get_response(sid) == first


def test_premature_submission_ignored_state_unchanged():
    engine = make_engine()
    survey, sid = start(engine, SCENARIOS[0], "en-IN")
    # Pending greeting Turn: an incomplete utterance changes nothing.
    assert engine.submit_answer(sid, "ok", utterance_complete=False) is AnswerReceipt.IGNORED
    greeting = engine.next_turn(sid)
    assert greeting.kind == "greeting"
    assert engine.submit_answer(sid, GREETING_REPLY, utterance_complete=True) is AnswerReceipt.PROCESSED
    # Question now pending; ignored submission leaves it exactly as is.
    assert engine.submit_answer(sid, "yes", utterance_complete=False) is AnswerReceipt.IGNORED
    question = engine.next_turn(sid)
    assert question.kind == "question"
    assert question.item_id == survey["items"][0]["item_id"]
    # After the question was taken, an ignored submission still leaves nothing queued.
    assert engine.submit_answer(sid, "yes", utterance_complete=False) is AnswerReceipt.IGNORED
    assert engine.next_turn(sid) is None
    # Real answer still works afterwards.
    assert engine.submit_answer(
        sid, good_answer(survey["items"][0]), utterance_complete=True
    ) is AnswerReceipt.PROCESSED


def test_ignored_submission_keeps_pending_turn():
    engine = make_engine()
    survey, sid = start(engine, SCENARIOS[0], "en-IN")
    assert engine.submit_answer(sid, "ok", utterance_complete=False) is AnswerReceipt.IGNORED
    first = engine.next_turn(sid)
    assert first is not None and first.kind == "greeting"


@pytest.mark.parametrize("op", ["next_turn", "submit_answer", "submit_event", "get_response"])
def test_unknown_session_raises(op):
    engine = make_engine()
    calls = {
        "next_turn": lambda: engine.next_turn("nope"),
        "submit_answer": lambda: engine.submit_answer("nope", "ok", utterance_complete=True),
        "submit_event": lambda: engine.submit_event("nope", Timeout()),
        "get_response": lambda: engine.get_response("nope"),
    }
    with pytest.raises(UnknownSession):
        calls[op]()


def test_finalised_session_raises_except_get_response():
    engine = make_engine()
    survey, sid = start(engine, SCENARIOS[0], "en-IN")
    play(engine, sid, survey)
    engine.get_response(sid)
    with pytest.raises(SessionFinalised):
        engine.next_turn(sid)
    with pytest.raises(SessionFinalised):
        engine.submit_answer(sid, "ok", utterance_complete=True)
    with pytest.raises(SessionFinalised):
        engine.submit_event(sid, Timeout())
    engine.get_response(sid)  # still allowed


def test_get_response_before_end_raises_not_ended():
    engine = make_engine()
    survey, sid = start(engine, SCENARIOS[0], "en-IN")
    with pytest.raises(NotEnded):
        engine.get_response(sid)
    engine.next_turn(sid)
    with pytest.raises(NotEnded):
        engine.get_response(sid)


def test_get_response_with_closing_turn_queued_raises_turns_pending():
    engine = make_engine()
    survey, sid = start(engine, SCENARIOS[0], "en-IN")
    items = {i["item_id"]: i for i in survey["items"]}
    while True:
        turn = engine.next_turn(sid)
        reply = GREETING_REPLY if turn.kind == "greeting" else good_answer(items[turn.item_id])
        engine.submit_answer(sid, reply, utterance_complete=True)
        # Last answer leaves the closing Turn queued.
        if turn.item_id == survey["items"][-1]["item_id"]:
            break
    with pytest.raises(TurnsPending):
        engine.get_response(sid)
    assert engine.next_turn(sid).kind == "closing"
    ResponseRecord.model_validate(engine.get_response(sid))


def test_public_api_is_exactly_five_operations():
    public = {n for n in dir(JaakEngine) if not n.startswith("_")}
    assert public == OPERATIONS
