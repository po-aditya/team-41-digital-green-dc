"""Schema loading, cross-ref resolution, format checking, and valid/invalid examples."""

from __future__ import annotations

import json

import pytest

from mel_agent.contracts import SchemaLoadError, SchemaName, SchemaRegistry

# ---------- loading ----------


def test_all_six_schemas_load(registry):
    assert set(registry.schemas) == set(SchemaName)
    for schema in registry.schemas.values():
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_missing_schema_dir_raises(tmp_path):
    with pytest.raises(SchemaLoadError):
        SchemaRegistry(tmp_path / "nope")


def test_all_cross_schema_refs_resolve_locally(registry):
    # Loading succeeded, so every $ref (including survey.schema.json#/$defs/...) resolved
    # from the local registry. Confirm the cross-file refs are really there.
    response_refs = json.dumps(registry.schemas[SchemaName.RESPONSE])
    assert "survey.schema.json#/$defs/ist_time" in response_refs


def test_unresolvable_ref_fails_at_load_without_network(tmp_path, settings):
    # A copy of the schemas (in tmp, so the originals are untouched) with one bad $ref.
    for name in SchemaName:
        (tmp_path / name.filename).write_text((settings.schemas_dir / name.filename).read_text())
    broken = json.loads((tmp_path / "response.schema.json").read_text())
    broken["properties"]["recorded_at"] = {"$ref": "does_not_exist.schema.json#/$defs/x"}
    (tmp_path / "response.schema.json").write_text(json.dumps(broken))
    with pytest.raises(SchemaLoadError, match="does_not_exist"):
        SchemaRegistry(tmp_path)


# ---------- every worked example in the pack is valid ----------


def _examples(pack_json, pattern):
    return sorted(pack_json.glob(pattern))


@pytest.mark.parametrize(
    "schema,pattern,min_count",
    [
        ("insight", "scenarios/*/insight.json", 6),
        ("survey", "scenarios/*/survey.*.json", 10),
        ("schedule_handoff", "scenarios/*/schedule_handoff.json", 5),
        ("no_survey", "scenarios/*/no_survey.json", 1),
        ("response", "scenarios/*/responses/*.json", 25),
        ("response", "outcomes/*/*/*.json", 183),
    ],
)
def test_pack_examples_are_valid(registry, pack_json, schema, pattern, min_count):
    files = _examples(pack_json, pattern)
    assert len(files) >= min_count
    failures = {}
    for f in files:
        errs = registry.errors(schema, json.loads(f.read_text(encoding="utf-8")))
        if errs:
            failures[str(f.relative_to(pack_json))] = errs[:3]
    assert not failures, failures


def test_bottom_sheet_renders_are_valid(registry, pack_json):
    # Render files wrap the bottom sheet with channel metadata; validate the sheet part.
    files = _examples(pack_json, "scenarios/*/render/*/app.json") + _examples(pack_json, "scenarios/*/render/*/web.json")
    assert len(files) == 20
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        sheet = {"presentation": doc["presentation"], "sheet": doc["sheet"]}
        assert registry.errors("bottom_sheet", sheet) == [], f


def test_clean_insights_from_dataset_are_valid(registry, settings):
    path = settings.participant_pack_dir / "data" / "insights.jsonl"
    checked = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("quality_flag") == "clean":
                assert registry.is_valid("insight", row), row["insight_id"]
                checked += 1
                if checked >= 500:
                    break
    assert checked == 500


# ---------- deliberately invalid examples are rejected ----------

SURVEY = "scenarios/1-mustard-aphid-spray/survey.hi-IN.json"
HANDOFF = "scenarios/1-mustard-aphid-spray/schedule_handoff.json"
RESPONSE = "scenarios/1-mustard-aphid-spray/responses/app.json"
INSIGHT = "scenarios/1-mustard-aphid-spray/insight.json"
NO_SURVEY = "scenarios/6-zero-tillage-info-no-survey/no_survey.json"
APP_RENDER = "scenarios/1-mustard-aphid-spray/render/en-IN/app.json"


def _assert_rejected(registry, schema, doc, keyword=None):
    errs = registry.errors(schema, doc)
    assert errs, "expected the document to be rejected"
    if keyword:
        assert any(e.validator == keyword for e in errs), [(e.path, e.validator, e.message) for e in errs]


def test_survey_rejects_bad_id(registry, load_example):
    doc = load_example(SURVEY)
    doc["survey_id"] = "SURVEY-1"
    _assert_rejected(registry, "survey", doc, "pattern")


def test_survey_rejects_too_many_items(registry, load_example):
    doc = load_example(SURVEY)
    doc["items"] = doc["items"] * 2
    _assert_rejected(registry, "survey", doc, "maxItems")


def test_survey_rejects_unknown_field(registry, load_example):
    doc = load_example(SURVEY)
    doc["extra"] = 1
    _assert_rejected(registry, "survey", doc, "additionalProperties")


def test_survey_rejects_option_label_over_20_chars(registry, load_example):
    doc = load_example(SURVEY)
    item = next(i for i in doc["items"] if "options" in i)
    item["options"][0]["label"] = "x" * 21
    _assert_rejected(registry, "survey", doc, "maxLength")


def test_survey_scale_item_rejects_options(registry, load_example):
    doc = load_example(SURVEY)
    doc["items"][0] = {
        "item_id": "q_scale",
        "type": "survey-scale",
        "prompt": "How bad?",
        "scale_min": 1,
        "scale_max": 5,
        "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
    }
    _assert_rejected(registry, "survey", doc, "not")


def test_format_checker_rejects_impossible_date(registry, load_example):
    # Matches the ist_time regex (\d{2}) but month 13 is not a real date-time:
    # only an active format checker catches this.
    doc = load_example(SURVEY)
    doc["send_window"]["not_before"] = "2026-13-45T10:00:00+05:30"
    _assert_rejected(registry, "survey", doc, "format")


def test_survey_rejects_non_ist_offset(registry, load_example):
    doc = load_example(SURVEY)
    doc["send_window"]["not_after"] = "2026-11-10T10:00:00Z"
    _assert_rejected(registry, "survey", doc, "pattern")


def test_handoff_cross_ref_into_survey_is_enforced(registry, load_example):
    # handoff.survey is "$ref": "survey.schema.json"; a broken nested survey must fail.
    doc = load_example(HANDOFF)
    del doc["survey"]["items"]
    _assert_rejected(registry, "schedule_handoff", doc, "required")


def test_handoff_rejects_bad_uuid(registry, load_example):
    doc = load_example(HANDOFF)
    doc["farmerchat_flow"]["flow_id"] = "not-a-uuid"
    _assert_rejected(registry, "schedule_handoff", doc, "format")


def test_response_cross_ref_ist_time_is_enforced(registry, load_example):
    # recorded_at is "$ref": "survey.schema.json#/$defs/ist_time".
    doc = load_example(RESPONSE)
    doc["recorded_at"] = "yesterday"
    _assert_rejected(registry, "response", doc)


def test_response_rejects_unknown_follow_up_reason(registry, load_example):
    doc = load_example(RESPONSE)
    doc["follow_up_reasons"] = ["farmer_unhappy"]
    _assert_rejected(registry, "response", doc, "enum")


def test_insight_rejects_missing_required(registry, load_example):
    doc = load_example(INSIGHT)
    del doc["resolution_type"]
    _assert_rejected(registry, "insight", doc, "required")


def test_no_survey_rejects_wrong_decision(registry, load_example):
    doc = load_example(NO_SURVEY)
    doc["decision"] = "survey"
    _assert_rejected(registry, "no_survey", doc, "const")


def test_bottom_sheet_rejects_four_steps(registry, load_example):
    doc = load_example(APP_RENDER)
    sheet = {"presentation": doc["presentation"], "sheet": doc["sheet"]}
    sheet["presentation"]["steps_total"] = 4
    _assert_rejected(registry, "bottom_sheet", sheet, "maximum")


def test_junk_rows_include_schema_failures(registry, settings):
    # Sanity check that the validator catches the pack's deliberately broken rows.
    path = settings.participant_pack_dir / "data" / "insights.jsonl"
    rejected = sum(
        1
        for line in path.open(encoding="utf-8")
        if (row := json.loads(line)).get("quality_flag") == "junk" and not registry.is_valid("insight", row)
    )
    assert rejected > 0
