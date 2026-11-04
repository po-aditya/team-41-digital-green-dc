"""Unit tests for the session state machine (task 5.3).

Covers Req 5.1 to 5.5, 5.10, 5.11, 10.1 to 10.7, 14.1.

Note on ``attempts`` semantics: ``ItemState.attempts`` is counted when a
question or re-ask Turn is QUEUED (not when it is taken by pop_turn, and not
when an answer arrives). So an Item shown once has attempts 1, an Item that was
re-asked has attempts 2, and an Item never reached has attempts 0.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mel_agent.jaak import session as S
from mel_agent.jaak.errors import OutOfOrder
from mel_agent.jaak.models import Survey
from mel_agent.jaak.templates import TemplateSet

ROOT = Path(__file__).resolve().parents[3]
SCEN = ROOT / "data" / "participant-pack" / "json" / "scenarios"
LANGS = ("en-IN", "hi-IN")
AT = datetime(2025, 1, 10, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
GIBBERISH = "zqxjv wkplm"  # unique marker, maps to nothing in either language


def ctx(lang: str) -> S.StepContext:
    return S.StepContext(TemplateSet.load(lang))


def load(scenario: str, lang: str) -> Survey:
    raw = json.loads((SCEN / scenario / f"survey.{lang}.json").read_text(encoding="utf-8"))
    return Survey.model_validate(raw)


def ans(text: str) -> S.AnswerInput:
    return S.AnswerInput(text=text, at=AT)


def good_answer(item) -> str:
    """A reply that maps to the first Option (or 3 on a scale)."""
    return "3" if item.type == "survey-scale" else item.options[0].label


def hand_survey(items: list[dict], lang: str = "en-IN") -> Survey:
    return Survey.model_validate({
        "survey_id": "S-00001",
        "farmer_id": "F-000001",
        "source_insight_ids": ["I-000001"],
        "language": lang,
        "send_window": {"not_before": "2025-01-10T08:00:00+05:30",
                        "not_after": "2025-01-11T08:00:00+05:30"},
        "items": items,
        "rationale": "test rationale",
    })


def select_item(item_id="q1"):
    return {"item_id": item_id, "type": "survey-single-select", "prompt": "Which one did you use",
            "options": [{"value": "a", "label": "Alpha"}, {"value": "b", "label": "Beta"}]}


def confirm_item(item_id="q1"):
    return {"item_id": item_id, "type": "survey-confirm", "prompt": "Did you spray",
            "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]}


def scale_item(item_id="q1"):
    return {"item_id": item_id, "type": "survey-scale", "prompt": "How satisfied are you",
            "scale_min": 1, "scale_max": 5}


def started(survey: Survey, c: S.StepContext):
    """Start and take the greeting; returns (state, greeting_turn)."""
    st, _ = S.step(S.initial_state(survey), S.StartInput(), c)
    return S.pop_turn(st)


def to_first_item(survey: Survey, c: S.StepContext, reply="ok"):
    """Run to the first question being queued; returns state with the question still queued."""
    st, _ = started(survey, c)
    st, turns = S.step(st, ans(reply), c)
    return st, turns


def drain(st):
    """Pop every queued Turn."""
    out = []
    while st.queue:
        st, t = S.pop_turn(st)
        out.append(t)
    return st, out


# --------------------------------------------------------------------------- #
# Order and one-at-a-time (5.1 to 5.5, 14.1)
# --------------------------------------------------------------------------- #
SCENARIOS = ["1-mustard-aphid-spray", "2-wheat-irrigation-timing", "3-potato-blight-wait",
             "4-cow-vet-escalation", "5-wheat-variety-plan"]


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_items_asked_one_at_a_time_in_order(scenario, lang):
    survey, c = load(scenario, lang), ctx(lang)
    st, greeting = started(survey, c)
    assert greeting.kind == "greeting"
    assert st.phase == S.PHASE_AWAIT_GREETING_REPLY

    st, turns = S.step(st, ans("ok"), c)
    seen = []
    for idx, item in enumerate(survey.items):
        # exactly one Turn queued, for the current Item, and nothing for later Items.
        assert len(turns) == 1 and len(st.queue) == 1
        assert turns[0].kind == "question" and turns[0].item_id == item.item_id
        assert st.item_index == idx
        assert all(s.attempts == 0 for s in st.items[idx + 1:])
        st, taken = S.pop_turn(st)
        seen.append(taken.item_id)
        st, turns = S.step(st, ans(good_answer(item)), c)
        assert st.items[idx].result == "answered"
    assert seen == [i.item_id for i in survey.items]
    # after the last Item: one closing Turn.
    assert [t.kind for t in turns] == ["closing"]


def test_start_queues_only_the_greeting():
    survey, c = load(SCENARIOS[0], "en-IN"), ctx("en-IN")
    st, turns = S.step(S.initial_state(survey), S.StartInput(), c)
    assert [t.kind for t in turns] == ["greeting"] and st.queue == turns
    assert all(s.attempts == 0 for s in st.items)


@pytest.mark.parametrize("lang", LANGS)
def test_closing_is_last_and_nothing_follows(lang):
    survey, c = load("3-potato-blight-wait", lang), ctx(lang)
    # last Item resolved: queued exactly one closing Turn and nothing else.
    st2, _ = to_first_item(survey, c)
    st2, _ = drain(st2)
    for item in survey.items[:-1]:
        st2, _ = S.step(st2, ans(good_answer(item)), c)
        st2, _ = drain(st2)
    st2, turns = S.step(st2, ans(good_answer(survey.items[-1])), c)
    assert [t.kind for t in turns] == ["closing"]
    assert [t.kind for t in st2.queue] == ["closing"]
    assert st2.phase == S.PHASE_CLOSING and st2.end == S.END_ALL_RESOLVED
    assert st2.closing_required and not st2.closing_delivered
    assert st2.ended


def test_popping_closing_ends_session():
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    st, turns = S.step(st, ans("Alpha"), c)
    assert st.phase == S.PHASE_CLOSING
    st, t = S.pop_turn(st)
    assert t.kind == "closing" and not t.expects_reply
    assert st.phase == S.PHASE_ENDED and st.closing_delivered and st.queue == ()
    # nothing more to pop
    again, none = S.pop_turn(st)
    assert none is None and again is st


def test_popping_greeting_moves_to_await_greeting_reply():
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    st, _ = S.step(S.initial_state(survey), S.StartInput(), c)
    assert st.phase == S.PHASE_GREETING
    st, t = S.pop_turn(st)
    assert t.kind == "greeting" and st.phase == S.PHASE_AWAIT_GREETING_REPLY


def test_pop_on_empty_queue_is_noop():
    survey = hand_survey([select_item()])
    st = S.initial_state(survey)
    new, t = S.pop_turn(st)
    assert t is None and new is st


# --------------------------------------------------------------------------- #
# Greeting reply (5.10, 5.11)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("reply", ["yes go ahead", "हाँ", GIBBERISH, "Alpha", ""])
def test_greeting_reply_is_not_an_answer_or_attempt(reply):
    survey, c = hand_survey([select_item(), select_item("q2")]), ctx("en-IN")
    st, _ = started(survey, c)
    st, turns = S.step(st, ans(reply), c)
    # the reply is discarded: Item 1 is asked (attempts 1 for the question only),
    # nothing is answered, and the reply text is not stored anywhere.
    assert [t.kind for t in turns] == ["question"] and turns[0].item_id == "q1"
    assert st.items[0].attempts == 1 and st.items[0].result == "pending"
    assert st.items[0].value is None and st.items[0].accepted_text is None
    assert st.items[1] == S.ItemState()
    assert st.answered_at is None
    assert st.phase == S.PHASE_AWAIT_ITEM
    outs = S.item_outcomes(st)
    assert outs[0].result == "skipped" and outs[0].value is None  # shown, unresolved
    assert outs[1].result == "not_reached" and outs[1].attempts == 0


def test_greeting_reply_text_not_in_state():
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    st, _ = started(survey, c)
    st, _ = S.step(st, ans(GIBBERISH), c)
    assert GIBBERISH not in repr(st)


# --------------------------------------------------------------------------- #
# Re-ask and invalid (10.1 to 10.7)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", LANGS)
def test_unclear_then_valid_is_answered_with_two_attempts(lang):
    survey, c = load("1-mustard-aphid-spray", lang), ctx(lang)
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    st, turns = S.step(st, ans(GIBBERISH), c)
    assert [t.kind for t in turns] == ["reask"] and turns[0].item_id == "q1"
    assert st.items[0].attempts == 2 and st.items[0].result == "pending"
    st, _ = drain(st)
    label = survey.items[0].options[0].label
    st, turns = S.step(st, ans(label), c)
    assert st.items[0].result == "answered"
    assert st.items[0].value == survey.items[0].options[0].value
    assert st.items[0].attempts == 2
    assert [t.kind for t in turns] == ["question"] and turns[0].item_id == "q2"
    out = S.item_outcomes(st)
    assert out[0].result == "answered" and out[0].attempts == 2
    assert out[0].raw_input == label
    assert out[1].result == "not_reached" or out[1].attempts == 1


@pytest.mark.parametrize("lang", LANGS)
def test_unclear_twice_is_invalid_with_null_value(lang):
    survey, c = load("1-mustard-aphid-spray", lang), ctx(lang)
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    st, _ = S.step(st, ans(GIBBERISH), c)
    st, _ = drain(st)
    st, turns = S.step(st, ans(GIBBERISH + " again"), c)
    it = st.items[0]
    assert it.result == "invalid" and it.value is None and it.attempts == 2
    assert it.accepted_text is None
    assert GIBBERISH not in repr(st)
    # moved on to the next Item, no third ask of Item 1
    assert [t.kind for t in turns] == ["question"] and turns[0].item_id == "q2"
    out = S.item_outcomes(st)[0]
    assert (out.result, out.value, out.attempts, out.raw_input) == ("invalid", None, 2, None)


def test_never_more_than_two_asks_per_item():
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    kinds = []
    for _ in range(2):
        st, turns = S.step(st, ans(GIBBERISH), c)
        kinds += [t.kind for t in turns]
        st, _ = drain(st)
    assert kinds == ["reask", "closing"]
    assert st.items[0].attempts == 2


def test_invalid_last_item_goes_to_closing():
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    st, _ = S.step(st, ans(GIBBERISH), c)
    st, _ = drain(st)
    st, turns = S.step(st, ans(GIBBERISH), c)
    assert [t.kind for t in turns] == ["closing"] and st.end == S.END_ALL_RESOLVED
    assert st.items[0].result == "invalid"


@pytest.mark.parametrize("lang", LANGS)
def test_reask_turn_has_only_prompt_labels_and_templates(lang):
    survey, c = load("1-mustard-aphid-spray", lang), ctx(lang)
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    st, (reask,) = S.step(st, ans(GIBBERISH), c)
    item = survey.items[0]
    assert reask.kind == "reask" and reask.expects_reply and reask.language == lang
    assert {s.source for s in reask.segments} <= {"survey_prompt", "option_label", "template"}
    assert [s.text for s in reask.segments if s.source == "survey_prompt"] == [item.prompt]
    assert [s.text for s in reask.segments if s.source == "option_label"] == \
        [o.label for o in item.options]
    # the unclear text is never echoed
    assert GIBBERISH not in reask.text
    assert all(GIBBERISH not in s.text for s in reask.segments)
    tmpl_ids = {s.ref for s in reask.segments if s.source == "template"}
    assert "reask_prefix" in tmpl_ids


def test_scale_item_reask_and_answer():
    survey, c = hand_survey([scale_item()]), ctx("en-IN")
    st, turns = to_first_item(survey, c)
    assert "1" in turns[0].text and "5" in turns[0].text
    st, _ = drain(st)
    st, (reask,) = S.step(st, ans("seven"), c)  # out of range -> unclear
    assert reask.kind == "reask" and "1" in reask.text and "5" in reask.text
    st, _ = drain(st)
    st, _ = S.step(st, ans("four"), c)
    assert st.items[0].result == "answered" and st.items[0].value == 4
    assert st.items[0].attempts == 2


def test_confirm_item_yes_no():
    survey, c = hand_survey([confirm_item()]), ctx("en-IN")
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    st, _ = S.step(st, ans("No"), c)
    assert st.items[0].value == "no" and st.items[0].attempts == 1


def test_single_item_survey_goes_straight_to_closing():
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    st, turns = S.step(st, ans("Beta"), c)
    assert [t.kind for t in turns] == ["closing"]
    assert st.items[0].value == "b" and st.answered_at == AT
    st, rest = drain(st)
    assert [t.kind for t in rest] == ["closing"] and st.phase == S.PHASE_ENDED


def test_answered_at_is_clock_of_last_accepted_answer():
    survey, c = hand_survey([select_item(), select_item("q2")]), ctx("en-IN")
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    t1 = AT + timedelta(minutes=1)
    st, _ = S.step(st, S.AnswerInput("Alpha", t1), c)
    assert st.answered_at == t1
    st, _ = drain(st)
    st, _ = S.step(st, S.AnswerInput(GIBBERISH, AT + timedelta(minutes=2)), c)
    assert st.answered_at == t1  # unclear does not move it


# --------------------------------------------------------------------------- #
# Privacy of stored text (10.6, 17 related)
# --------------------------------------------------------------------------- #
def test_unclear_text_never_in_state_but_accepted_text_is():
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    st, _ = S.step(st, ans(GIBBERISH), c)
    assert GIBBERISH not in repr(st)
    for f in dataclasses.fields(st.items[0]):
        assert GIBBERISH not in repr(getattr(st.items[0], f.name))
    st, _ = drain(st)
    st, _ = S.step(st, ans("Alpha"), c)
    assert st.items[0].accepted_text == "Alpha"
    assert GIBBERISH not in repr(st)


def test_accepted_text_truncated_to_256():
    survey, c = hand_survey([select_item(), scale_item("q2")]), ctx("en-IN")
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    st, _ = S.step(st, ans("Alpha" + " " * 400), c)
    kept = st.items[0].accepted_text
    assert st.items[0].result == "answered" and len(kept) == S.RAW_TEXT_MAX == 256
    assert kept == ("Alpha" + " " * 400)[:256]
    st, _ = drain(st)
    st, _ = S.step(st, ans("3" + " " * 300), c)
    assert len(st.items[1].accepted_text) == 256


# --------------------------------------------------------------------------- #
# Purity
# --------------------------------------------------------------------------- #
def test_step_does_not_mutate_input_state_and_is_deterministic():
    survey, c = hand_survey([select_item(), select_item("q2")]), ctx("en-IN")
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    before, before_repr = st, repr(st)
    r1 = S.step(st, ans("Alpha"), c)
    r2 = S.step(st, ans("Alpha"), c)
    assert st == before and repr(st) == before_repr
    assert r1 == r2
    assert r1[0] is not st
    # unclear path too
    u1, u2 = S.step(st, ans(GIBBERISH), c), S.step(st, ans(GIBBERISH), c)
    assert u1 == u2 and st == before


def test_state_is_frozen():
    st = S.initial_state(hand_survey([select_item()]))
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.phase = "ended"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.items[0].attempts = 5  # type: ignore[misc]


def test_failed_step_leaves_state_unchanged():
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    st, _ = S.step(S.initial_state(survey), S.StartInput(), c)
    before = st
    with pytest.raises(OutOfOrder):
        S.step(st, S.StartInput(), c)
    assert st == before


# --------------------------------------------------------------------------- #
# Out of order and not implemented
# --------------------------------------------------------------------------- #
def test_second_start_raises_out_of_order():
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    st, _ = S.step(S.initial_state(survey), S.StartInput(), c)
    with pytest.raises(OutOfOrder):
        S.step(st, S.StartInput(), c)
    taken, _ = S.pop_turn(st)
    with pytest.raises(OutOfOrder):
        S.step(taken, S.StartInput(), c)


def test_answer_before_start_raises_out_of_order():
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    with pytest.raises(OutOfOrder):
        S.step(S.initial_state(survey), ans("hello"), c)


def test_answer_when_greeting_not_yet_taken_raises_out_of_order():
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    st, _ = S.step(S.initial_state(survey), S.StartInput(), c)
    assert st.phase == S.PHASE_GREETING
    with pytest.raises(OutOfOrder):
        S.step(st, ans("hello"), c)


def test_answer_after_end_raises_out_of_order():
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    st, _ = to_first_item(survey, c)
    st, _ = drain(st)
    st, _ = S.step(st, ans("Alpha"), c)
    with pytest.raises(OutOfOrder):  # closing queued (phase closing)
        S.step(st, ans("more"), c)
    st, _ = drain(st)
    assert st.phase == S.PHASE_ENDED
    with pytest.raises(OutOfOrder):
        S.step(st, ans("more"), c)


@pytest.mark.parametrize("inp", [S.TimeoutInput(), S.NotNowInput(), S.OptOutInput(),
                                 S.FailureInput("voice_busy")])
def test_not_implemented_inputs_raise(inp):
    survey, c = hand_survey([select_item()]), ctx("en-IN")
    st, _ = started(survey, c)
    with pytest.raises(NotImplementedError):
        S.step(st, inp, c)
    # also from the initial phase
    with pytest.raises(NotImplementedError):
        S.step(S.initial_state(survey), inp, c)
