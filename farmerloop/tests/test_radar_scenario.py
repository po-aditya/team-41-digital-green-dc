"""Scenario contracts and independent fixture oracles, not a Radar engine."""

from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
import subprocess
import sys

import pytest

from farmerloop.models import Insight
from farmerloop.radar.scenario import VARIANTS, build_scenario
from farmerloop.radar.survey import input_access_survey
from farmerloop.respond import ItemObservation, build_response
from farmerloop.simulate import format_raw
from farmerloop.timing import compute_window
from farmerloop.validate import validate


@pytest.fixture(scope="module")
def base():
    return build_scenario()


@pytest.mark.parametrize("language", ["hi-IN", "en-IN"])
def test_full_pipeline_contracts_and_provenance(language):
    s = build_scenario(language=language)
    assert s.synthetic is True
    assert len(s.targets) == len(s.insights) == len(s.decisions) == len(s.surveys) == len(s.handoffs) == len(s.responses) == 60
    for records, key in ((s.insights, "insight_id"), (s.targets, "farmer_id"),
                         (s.surveys, "survey_id"), (s.responses, "response_key")):
        assert len({r[key] for r in records}) == 60
    for target, insight, decision, survey, handoff, response in zip(
            s.targets, s.insights, s.decisions, s.surveys, s.handoffs, s.responses):
        for name, record in (("insight", insight), ("survey", survey),
                             ("schedule_handoff", handoff), ("response", response)):
            assert validate(name, record) == []
        assert target["farmer_id"].startswith("SIM-F-")
        assert response["response_key"].startswith("sim-")
        assert decision["survey"] and decision["rule"] == "R8"
        assert decision["insight_id"] == insight["insight_id"] == target["insight_id"]
        assert survey["farmer_id"] == response["farmer_id"] == target["farmer_id"] == insight["farmer_id"]
        assert response["survey_id"] == survey["survey_id"] == target["survey_id"]
        assert response["source_insight_ids"] == survey["source_insight_ids"] == [insight["insight_id"]]
        assert response["language"] == survey["language"] == language
        assert handoff["survey"] == survey
        assert handoff["handoff_id"] == target["handoff_id"]
        assert handoff["channel_order"] == [{"channel": "whatsapp", "wait_hours": None}]
        parse = datetime.fromisoformat
        assert parse(handoff["created_at"]) < parse(target["due_at"]) <= parse(response["timestamps"]["sent"])
        assert parse(response["timestamps"]["sent"]) <= parse(survey["send_window"]["not_after"])
        assert parse(response["recorded_at"]) <= parse(handoff["expires_at"]) < parse(s.observation_cutoff)


def test_comparable_context_and_no_official_farmer_ids(base):
    # Geography and identifiers change; agricultural conditions do not.
    common = ("asset", "concern", "advice_summary", "query_summary", "created_at",
              "verification", "action_window_days", "resolution_type", "preferred_channel")
    for insight in base.insights:
        assert all(insight[key] == base.insights[0][key] for key in common)
        assert "synthetic" in insight["location"]["district"]
    assert Counter(t["district_key"] for t in base.targets) == {"A": 30, "B": 30}


@pytest.mark.parametrize("variant", VARIANTS)
def test_reproducible_independent_snapshots(variant):
    s = build_scenario(variant=variant)
    serialized = json.dumps(s.dump(), sort_keys=True, ensure_ascii=False)
    assert serialized == json.dumps(build_scenario(variant=variant).dump(), sort_keys=True, ensure_ascii=False)
    exported = s.dump()
    exported["targets"][0]["farmer_id"] = "changed"
    assert s.targets[0]["farmer_id"] == "SIM-F-A-001"


@pytest.mark.parametrize("variant", VARIANTS)
def test_exact_fixture_counts_and_variant_oracles(variant):
    s = build_scenario(variant=variant)
    # Independent counts inspect produced records. Expected metadata never
    # drives the generator's records and will not drive future analytics.
    for district in ("A", "B"):
        targets = [t for t in s.targets if t["district_key"] == district]
        surveys = {t["survey_id"] for t in targets}
        rows = [r for r in s.responses if r["survey_id"] in surveys]
        valid = [r for r in rows if not validate("response", r)]
        unique = {r["response_key"]: r for r in valid}
        records = list(unique.values())
        expected = s.expected[district]
        assert len(targets) == expected["targets"] == 30
        assert len(records) == expected["attempts"]
        assert sum(r["timestamps"]["delivered"] is not None for r in records) == expected["delivered"]
        assert sum("q2" in r["answers"] for r in records) == expected["barrier_answers"]
        assert sum(r["complete"] for r in records) == expected["complete_responses"]
        assert sum(r["answers"].get("q2") == "could_not_obtain" for r in records) == expected["barrier_reports"]
        for status, key in (("delivery_failed", "delivery_failures"), ("expired", "expired_without_answer"),
                            ("partial", "partial_responses"), ("invalid_input", "invalid_input_responses")):
            assert sum(r["status"] == status for r in records) == expected[key]
        assert len(rows) - len(valid) == expected["malformed_response_records"]
        assert len(valid) - len(unique) == expected["replayed_records"]
        assert len(surveys - {r["survey_id"] for r in rows}) == expected["missing_response_records"]
    if variant == "base":
        # Fixed independent acceptance numbers, not just self-consistency.
        assert [s.expected[d]["delivered"] for d in ("A", "B")] == [27, 15]
        assert [s.expected[d]["barrier_answers"] for d in ("A", "B")] == [22, 5]
        assert [s.expected[d]["barrier_reports"] for d in ("A", "B")] == [10, 0]


def test_replay_is_exact_and_independent():
    s = build_scenario(variant="replay")
    assert s.responses[0] == s.responses[-1]
    s.responses[-1]["answers"]["q2"] = "changed"
    assert s.responses[0]["answers"]["q2"] == "could_not_obtain"


@pytest.mark.parametrize("language", ["hi-IN", "en-IN"])
def test_not_trying_does_not_imply_input_access_barrier(language):
    s = build_scenario(language=language)
    survey = s.surveys[0]
    observations = {}
    for item, value in zip(survey["items"], ("no", "not_tried")):
        raw, kind = format_raw(survey, item, value, "whatsapp")
        observations[item["item_id"]] = ItemObservation(shown=True, raw_input=raw, input_kind=kind)
    original = s.responses[0]
    record = build_response(survey, channel="whatsapp", items=observations,
                            timestamps=original["timestamps"], recorded_at=original["recorded_at"],
                            response_key="sim-not-tried", answered_by=survey["farmer_id"])
    assert record["complete"]
    assert record["status"] == "completed"
    assert record["follow_up_reasons"] == []
    assert not record["needs_follow_up"]


def test_only_explicit_access_answer_triggers_barrier(base):
    flagged = [r for r in base.responses if r["needs_follow_up"]]
    assert len(flagged) == 10
    for r in flagged:
        assert r["answers"] == {"q1": "yes", "q2": "could_not_obtain"}
        assert r["follow_up_reasons"] == ["could_not_get_input"]
        assert r["status"] == "negative_outcome"
        assert r["complete"]  # Negative is not the opposite of complete.


@pytest.mark.parametrize("field,value", [("concern", "pest_disease"),
                                        ("conversation_language", "fr-FR"),
                                        ("resolution_type", "direct_action")])
def test_template_rejects_unsupported_context(base, field, value):
    raw = deepcopy(base.insights[0])
    raw[field] = value
    insight = Insight.model_validate(raw)
    window = compute_window(insight.created_at, insight.verification.timing, insight.action_window_days)
    with pytest.raises(ValueError):
        input_access_survey(insight, window)


def test_invalid_scenario_arguments():
    with pytest.raises(ValueError):
        build_scenario(variant="typo")
    with pytest.raises(ValueError):
        build_scenario(language="fr-FR")


def test_cli_json_is_a_complete_synthetic_envelope():
    result = subprocess.run([sys.executable, "-B", "-m", "farmerloop.radar_demo", "--json"],
                            capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    assert payload["synthetic"] is True
    assert len(payload["targets"]) == len(payload["responses"]) == 60
    assert "analysis" not in payload
