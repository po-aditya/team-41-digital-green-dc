import json

import pytest

from mel_agent.data.pack import OutcomeCodes, PackError, PackPaths, Rules, pack_paths


def test_pack_paths_resolve(settings):
    paths = pack_paths(settings).require()
    for p in (paths.insights_jsonl, paths.insights_csv, paths.farmers_csv, paths.crop_calendar_csv, paths.golden_jsonl, paths.rules_json, paths.outcome_codes_json):
        assert p.is_file(), p


def test_missing_pack_is_reported(tmp_path):
    with pytest.raises(PackError, match="incomplete"):
        PackPaths(tmp_path).require()


def test_rules_values_come_from_file(rules, settings):
    raw = json.loads(pack_paths(settings).rules_json.read_text())
    assert rules.survey_for_resolution("direct_action") is True
    assert rules.survey_for_resolution("generic_information") is False
    assert rules.survey_for_resolution("nonsense") is None
    assert rules.season_end == raw["window_rules"]["season_end"] == "2027-03-31"
    assert rules.wait_hours_by_priority == raw["wait_hours_by_priority"]
    assert rules.channel_by_method["ivr_callback"] == "voice"


def test_rules_missing_key_fails_fast():
    with pytest.raises(PackError, match="missing keys"):
        Rules({"survey_by_resolution": {}})


def test_outcome_codes(outcome_codes):
    assert outcome_codes.failure("voice_busy")["retry_decision"] == "retry_same_channel"
    assert "wa_undelivered" in outcome_codes.failures_for_channel("whatsapp")
    assert "wa_undelivered" not in outcome_codes.failures_for_channel("voice")
    assert outcome_codes.success("negative_outcome")["counts_toward_cap"] is True
    with pytest.raises(PackError):
        OutcomeCodes({"success": {}})
