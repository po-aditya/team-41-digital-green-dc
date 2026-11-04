"""Deterministic, source-linked scenario built through the existing pipeline.

Expected counts are fixture oracles only, not an analytics implementation.
Variants deliberately alter the response stream while retaining all targets.
"""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import json

from ..config import PARTICIPANT_PACK
from ..decide import decide
from ..models import Insight
from ..schedule import build_handoff
from ..simulate import simulate
from ..timing import compute_window
from ..validate import validate
from .models import Scenario
from .survey import input_access_survey

TEMPLATE = "json/scenarios/5-wheat-variety-plan/insight.json"
VARIANTS = ("base", "replay", "missing", "malformed", "partial", "invalid_input")


def _checked(schema: str, record: dict) -> None:
    errors = validate(schema, record)
    if errors:
        raise ValueError(f"Synthetic {schema} failed validation: {errors}")


def build_scenario(*, language: str = "hi-IN", variant: str = "base") -> Scenario:
    """Build 60 fictional farmers; never write to the official participant pack.

    One due survey and one scripted attempt per farmer in base. No production
    delivery, persistent scheduler, or regional-population claim is implied.
    """
    if variant not in VARIANTS:
        raise ValueError(f"Unknown scenario variant: {variant}")
    if language not in ("hi-IN", "en-IN"):
        raise ValueError("Scenario supports hi-IN and en-IN only")
    template = json.loads((PARTICIPANT_PACK / TEMPLATE).read_text(encoding="utf-8"))
    _checked("insight", template)
    scenario = Scenario(
        scenario_id=f"sim-radar-seed-access-v1-{language}-{variant}",
        synthetic=True,
        description="Entirely synthetic demonstration; District A and B are fictional. Not evidence about Bihar farmers.",
        observation_cutoff="2026-12-30T19:00:00+05:30",
        context={"crop": "wheat", "growth_stage": "pre-sowing (schema null)",
                 "season": "rabi-2026-2027", "advice_topic": "variety_selection",
                 "survey_objective": "recommended_seed_access", "language": language,
                 "channel": "whatsapp", "barrier_item_id": "q2"},
        source_template=TEMPLATE,
        targets=[], insights=[], decisions=[], surveys=[], handoffs=[], responses=[],
        expected={}, variant_notes="Base fixture: no retries or replayed records.",
    )
    # Independent scenario specification, not rates calculated from outputs.
    for district, delivered, responded, barriers in (("A", 27, 22, 10), ("B", 15, 5, 0)):
        scenario.expected[district] = dict(
            targets=30, attempts=30, delivered=delivered,
            barrier_answers=responded, complete_responses=responded,
            barrier_reports=barriers, delivery_failures=30-delivered,
            expired_without_answer=delivered-responded,
            partial_responses=0, invalid_input_responses=0,
            missing_response_records=0, malformed_response_records=0, replayed_records=0,
        )
        for number in range(1, 31):
            suffix = f"{district}-{number:03d}"
            raw = deepcopy(template)
            raw.update(insight_id=f"SIM-I-{suffix}", farmer_id=f"SIM-F-{suffix}",
                       conversation_id=f"SIM-C-{suffix}", conversation_language=language,
                       preferred_channel="whatsapp")
            raw["location"]["district"] = f"District {district} (synthetic)"
            raw["verification"]["method"] = "whatsapp"
            _checked("insight", raw)
            insight = Insight.model_validate(raw)
            decision = decide(insight, schema_ok=True)
            window = compute_window(insight.created_at, insight.verification.timing,
                                    insight.action_window_days)
            if not decision.survey or window is None:
                raise ValueError("Synthetic insight must be eligible and schedulable")
            survey = input_access_survey(insight, window)
            handoff = build_handoff(insight, survey, window,
                                    created_at="2026-12-24T19:00:00+05:30")
            _checked("schedule_handoff", handoff)
            case = ("negative_outcome" if number <= barriers else
                    "completed" if number <= responded else
                    "window_expired" if number <= delivered else "wa_undelivered")
            # Existing simulator accepts naive IST dates (not UTC dates).
            sent = datetime.fromisoformat(handoff["send_window"]["not_before"]).replace(
                hour=9, tzinfo=None)
            expiry = datetime.fromisoformat(handoff["expires_at"]).replace(tzinfo=None)
            response = simulate(survey, "whatsapp", case, sent_at=sent, expires_at=expiry)
            scenario.targets.append(dict(
                target_id=f"sim-target-{suffix}", district_key=district,
                farmer_id=insight.farmer_id, insight_id=insight.insight_id,
                survey_id=survey.survey_id, handoff_id=handoff["handoff_id"],
                due_at=handoff["send_window"]["not_before"],
            ))
            scenario.insights.append(raw)
            scenario.decisions.append(asdict(decision))
            scenario.surveys.append(survey.dump())
            scenario.handoffs.append(handoff)
            scenario.responses.append(response)

    # Alter the first A barrier response only. All 60 target records survive.
    expected = scenario.expected["A"]
    if variant == "replay":
        scenario.responses.append(deepcopy(scenario.responses[0]))
        expected["replayed_records"] = 1
        scenario.variant_notes = "Exact replay of the first response; 61 records, 60 distinct attempts. Counts must not increase."
    elif variant in ("missing", "malformed"):
        if variant == "missing":
            scenario.responses.pop(0)
            expected["missing_response_records"] = 1
        else:
            scenario.responses[0]["answers"] = ["deliberately malformed synthetic record"]
            expected["malformed_response_records"] = 1
        expected.update(attempts=29, delivered=26, barrier_answers=21,
                        complete_responses=21, barrier_reports=9)
        scenario.variant_notes = "First A attempt evidence is missing/unusable. Retain its target; delivery is unknown, not failed. Malformed variant intentionally fails the response schema."
    elif variant in ("partial", "invalid_input"):
        case = "partial" if variant == "partial" else "free_text_instead_of_choice"
        handoff = scenario.handoffs[0]
        sent = datetime.fromisoformat(handoff["send_window"]["not_before"]).replace(hour=9, tzinfo=None)
        scenario.responses[0] = simulate(scenario.surveys[0], "whatsapp", case, sent_at=sent)
        expected.update(barrier_answers=21, complete_responses=21, barrier_reports=9)
        expected["partial_responses" if variant == "partial" else "invalid_input_responses"] = 1
        scenario.variant_notes = "First A farmer has an accepted q1 answer but no valid q2 barrier answer. Delivery remains confirmed; q1 alone cannot establish an access barrier."
    return scenario
