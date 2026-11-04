import json

import pytest

from mel_agent.rules.timing import SendWindow, TimingError, WindowAfterSeason, compute_send_window


def test_reproduces_every_worked_scenario_window(scenario_dirs, rules):
    checked = 0
    for d in scenario_dirs:
        if not (d / "schedule_handoff.json").exists():
            continue
        insight = json.loads((d / "insight.json").read_text())
        expected = json.loads((d / "schedule_handoff.json").read_text())["send_window"]
        assert compute_send_window(insight, rules).to_contract() == expected, d.name
        checked += 1
    assert checked == 5


@pytest.fixture
def base(load_example):
    return load_example("scenarios/1-mustard-aphid-spray/insight.json")  # created 2026-12-04


@pytest.mark.parametrize("timing,awd,start,end", [
    ("same_day", None, 1, 3),              # [0,1] -> earliest day 1, widened to 2 days
    ("next_day", 1, 1, 3),
    ("two_to_five_days", 2, 2, 5),
    ("two_to_five_days", 5, 5, 7),         # start pushed to action-window end, then widened
    ("three_to_ten_days", 5, 5, 10),
    ("seven_to_fourteen_days", 23, 23, 25),
    ("seasonal", None, 21, 45),
    ("none", 4, 5, 11),                     # action window + 1 .. + 7
    ("none", None, 3, 9),                   # null action window -> 2 days assumed
])
def test_day_offsets(base, rules, timing, awd, start, end):
    base["verification"]["timing"] = timing
    base["action_window_days"] = awd
    w = compute_send_window(base, rules)
    assert isinstance(w, SendWindow)
    assert (w.start_day_offset, w.end_day_offset) == (start, end)
    assert w.not_before.strftime("%H:%M") == "07:00" and w.not_after.strftime("%H:%M") == "19:00"
    assert w.not_before.date().isoformat() > base["created_at"][:10] == "2026-12-04"


def test_window_never_opens_on_advice_day(base, rules):
    base["verification"]["timing"] = "same_day"; base["action_window_days"] = 0
    assert compute_send_window(base, rules).not_before.date().isoformat() == "2026-12-05"


def test_season_end_clamps_or_rejects(base, rules):
    base["created_at"] = "2027-03-25T10:00:00+05:30"; base["verification"]["timing"] = "three_to_ten_days"; base["action_window_days"] = 3
    w = compute_send_window(base, rules)
    assert w.clamped_to_season_end and w.not_after.date().isoformat() == "2027-03-31"
    base["created_at"] = "2027-03-29T10:00:00+05:30"
    w = compute_send_window(base, rules)
    assert isinstance(w, WindowAfterSeason) and w.would_start.isoformat() == "2027-04-01"


def test_unknown_timing_rejected(base, rules):
    base["verification"]["timing"] = "whenever"
    with pytest.raises(TimingError):
        compute_send_window(base, rules)


def test_contract_strings_match_ist_pattern(base, rules, registry, load_example):
    w = compute_send_window(base, rules).to_contract()
    survey = load_example("scenarios/1-mustard-aphid-spray/survey.en-IN.json")
    assert not registry.errors("survey", {**survey, "send_window": w})
