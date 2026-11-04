"""Scheduler and broadcaster simulation: weekly cap and follow-up routing."""
import copy
from datetime import datetime, timedelta

import pytest

from conftest import GOOD_EN, make_survey
from mel_agent import data, rules, season
from mel_agent.rules import IST, parse_ts

FARMER = "F-TEST01"


def _handoffs(insight, days=(1, 2, 3)):
    """Three normal-priority surveys for one farmer, from advice given on 1, 2 and 3 Dec 2026."""
    out = []
    for n, day in enumerate(days, 1):
        ins = copy.deepcopy(insight)
        ins.update(insight_id=f"I-90000{n}", farmer_id=FARMER, created_at=f"2026-12-0{day}T10:00:00+05:30")
        d = rules.decide(ins)
        assert d.survey and d.priority == "normal"
        s = make_survey(ins, GOOD_EN["items"])
        h = rules.build_handoff(s, d, ins)
        assert data.schema_errors("schedule_handoff", h) == []
        assert h["frequency_cap"]["exempt"] is False
        out.append(h)
    return out


def test_weekly_cap_sends_only_one_per_week(insight):
    hs = _handoffs(insight)
    first_open = min(parse_ts(h["send_window"]["not_before"]) for h in hs)
    S = season.Season(hs, start=datetime(2026, 12, 1, tzinfo=IST), interactive_farmers=[FARMER])
    S.advance(datetime(2026, 12, 20, tzinfo=IST))

    sends = sorted(parse_ts(h["at"]) for it in S.items.values() for h in it["history"])
    in_week = [t for t in sends if first_open <= t < first_open + timedelta(days=7)]
    assert len(in_week) == 1
    assert S.cap_violations() == []
    states = sorted(it["state"] for it in S.items.values())
    assert states.count("dropped_capped") == 2


@pytest.mark.parametrize("seed", range(10))
def test_weekly_cap_holds_with_simulated_failures(insight, seed):
    S = season.Season(_handoffs(insight), start=datetime(2026, 12, 1, tzinfo=IST), seed=seed)
    S.advance(datetime(2026, 12, 20, tzinfo=IST))
    assert S.cap_violations() == []
    asked = {r["survey_id"] for r in S.responses if r["counts_toward_cap"]}
    assert len(asked) <= 1
    assert all(data.schema_errors("response", r) == [] for r in S.responses)


def test_negative_answer_goes_to_follow_up_queue(insight):
    (h,) = _handoffs(insight, days=(1,))
    sid = h["survey"]["survey_id"]
    S = season.Season([h], start=datetime(2026, 12, 1, tzinfo=IST), interactive_farmers=[FARMER])
    S.advance(parse_ts(h["send_window"]["not_before"]) + timedelta(hours=1))
    assert [it["handoff"]["survey"]["survey_id"] for it in S.inbox(FARMER)] == [sid]

    rec = S.answer(sid, {"q1": "yes", "q2": "worse"})
    assert rec["status"] == "negative_outcome"
    assert rec["needs_follow_up"] is True
    assert data.schema_errors("response", rec) == []
    assert len(S.follow_up_queue) == 1
    assert S.follow_up_queue[0]["survey_id"] == sid
    assert S.follow_up_queue[0]["reasons"] == ["crop_or_animal_damaged"]


def test_positive_answer_does_not_go_to_follow_up_queue(insight):
    (h,) = _handoffs(insight, days=(1,))
    S = season.Season([h], start=datetime(2026, 12, 1, tzinfo=IST), interactive_farmers=[FARMER])
    S.advance(parse_ts(h["send_window"]["not_before"]) + timedelta(hours=1))
    rec = S.answer(h["survey"]["survey_id"], {"q1": "yes", "q2": "better"})
    assert rec["status"] == "completed"
    assert S.follow_up_queue == []


def test_simulated_negative_outcomes_all_reach_the_queue(insight):
    hs = []
    for n in range(40):
        ins = copy.deepcopy(insight)
        ins.update(insight_id=f"I-8{n:05d}", farmer_id=f"F-SIM{n:03d}")
        hs.append(rules.build_handoff(make_survey(ins, GOOD_EN["items"]), rules.decide(ins), ins))
    S = season.Season(hs, start=datetime(2026, 12, 1, tzinfo=IST), seed=3)
    S.advance(datetime(2026, 12, 20, tzinfo=IST))
    negative = [r for r in S.responses if r["needs_follow_up"]]
    assert negative, "the simulation should produce some bad outcomes"
    assert {r["survey_id"] for r in negative} == {f["survey_id"] for f in S.follow_up_queue}
    assert len(negative) == len(S.follow_up_queue)
