"""Rebuild every official response example and compare derived fields.

For each of the 183 outcome-grid records and the 25 scenario responses we feed
build_response ONLY the observations the record describes:
  * the survey (looked up by survey_id + language in the scenario surveys),
  * channel, timestamps, recorded_at, response_key, delivery_attempt,
    answered_by, raw_event, question_type,
  * per question: shown or not, raw_input, input_kind, attempts,
  * the external event, taken from the grid file NAME (the case label) and only
    for events that cannot be derived (delivery failures, declines, expiry,
    duplicates, stale taps, sheet cases).
Every other field is derived by the implementation and compared with the
official record. Nothing in the implementation reads these files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from farmerloop import config, outcomes
from farmerloop.respond import ItemObservation, build_response

PACK = config.PARTICIPANT_PACK / "json"
GRID_DIR = PACK / "outcomes"
SCENARIO_DIR = PACK / "scenarios"

# Fields copied from the record as observations (not derived).
OBSERVED = {"response_key", "channel", "timestamps", "recorded_at", "delivery_attempt",
            "answered_by", "raw_event", "question_type"}
OBSERVED_ITEM = {"item_id", "raw_input", "input_kind", "attempts"}

# Cases whose outcome the implementation must derive (never passed as events).
DERIVED_CASES = {"completed", "negative_outcome", "partial", "identity_mismatch",
                 "free_text_instead_of_choice", "keypad_out_of_range", "speech_not_understood"}


def _surveys() -> dict[tuple[str, str], dict]:
    out = {}
    for f in SCENARIO_DIR.glob("*/survey.*.json"):
        s = json.loads(f.read_text(encoding="utf-8"))
        out[(s["survey_id"], s["language"])] = s
    return out


SURVEYS = _surveys()


def _cases() -> list[tuple[str, Path, str | None]]:
    cases = []
    for f in sorted(GRID_DIR.rglob("*.json")):
        stem = f.stem
        event = None if stem in DERIVED_CASES else stem
        cases.append((str(f.relative_to(PACK)), f, event))
    for f in sorted(SCENARIO_DIR.glob("*/responses/*.json")):
        # Scenario responses are all success records; no event to supply.
        cases.append((str(f.relative_to(PACK)), f, None))
    return cases


CASES = _cases()


def _rebuild(official: dict, event: str | None) -> dict:
    survey = SURVEYS[(official["survey_id"], official["language"])]
    obs = {
        i["item_id"]: ItemObservation(
            shown=i["result"] != "not_reached",
            raw_input=i["raw_input"],
            input_kind=i["input_kind"],
            attempts=i["attempts"],
        )
        for i in official["items"]
    }
    return build_response(
        survey,
        channel=official["channel"],
        items=obs,
        timestamps=official["timestamps"],
        recorded_at=official["recorded_at"],
        response_key=official["response_key"],
        answered_by=official["answered_by"],
        event=event,
        delivery_attempt=official["delivery_attempt"],
        raw_event=official["raw_event"],
        question_type=official.get("question_type"),
    )


def _diff(official: dict, built: dict) -> list[str]:
    diffs = []
    for key in sorted(set(official) | set(built)):
        if key in OBSERVED or key == "items":
            continue
        if official.get(key) != built.get(key):
            diffs.append(f"{key}: official={official.get(key)!r} built={built.get(key)!r}")
    for o, b in zip(official["items"], built["items"]):
        for key in sorted(set(o) - OBSERVED_ITEM):
            if o.get(key) != b.get(key):
                diffs.append(f"items[{o['item_id']}].{key}: official={o.get(key)!r} built={b.get(key)!r}")
    if len(official["items"]) != len(built["items"]):
        diffs.append(f"item count: official={len(official['items'])} built={len(built['items'])}")
    return diffs


def test_case_counts():
    assert sum(1 for c in CASES if "/outcomes/" in f"/{c[0]}") == 183
    assert sum(1 for c in CASES if "/responses/" in c[0]) == 25


def test_every_case_event_is_a_real_rule():
    # Guards against a misspelt file-name event silently becoming "no event".
    known = outcomes.failure_codes() | outcomes.sheet_cases() | DERIVED_CASES
    assert {Path(c[0]).stem for c in CASES if "outcomes/" in c[0]} <= known


@pytest.mark.parametrize("name, path, event", CASES, ids=[c[0] for c in CASES])
def test_rebuilt_record_matches_official(name, path, event):
    official = json.loads(path.read_text(encoding="utf-8"))
    built = _rebuild(official, event)
    diffs = _diff(official, built)
    assert not diffs, f"{name}:\n  " + "\n  ".join(diffs)
