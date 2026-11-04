"""Deterministic ID tests. Full 6,999-row uniqueness is in scripts/verify_ids.py."""

import re
import uuid

from farmerloop import ids
from farmerloop.dataio import load_golden


def test_ids_match_schema_patterns():
    sid = ids.survey_id("I-000263")
    assert re.fullmatch(r"S-[0-9]{10}", sid)
    assert re.fullmatch(r"H-[0-9]{10}", ids.handoff_id(sid))
    assert re.fullmatch(r"[a-z][a-z0-9_]{1,63}", ids.flow_key(sid))
    uuid.UUID(ids.flow_id(sid))
    uuid.UUID(ids.campaign_id())


def test_ids_are_deterministic():
    assert ids.survey_id("I-000263") == ids.survey_id("I-000263")
    assert ids.flow_id("S-1234567890") == ids.flow_id("S-1234567890")
    assert ids.campaign_id() == ids.campaign_id()


def test_flow_key_format():
    assert ids.flow_key("S-1234567890") == "mel_s_1234567890"


def test_different_inputs_give_different_ids():
    assert ids.survey_id("I-000001") != ids.survey_id("I-000002")


def test_golden_ids_unique_across_all_families():
    load = load_golden()
    assert load.errors == []
    insight_ids = [c.insight_id for c in load.cases]
    assert len(set(insight_ids)) == len(insight_ids) == 150
    survey_ids = [ids.survey_id(i) for i in insight_ids]
    for family in (
        survey_ids,
        [ids.handoff_id(s) for s in survey_ids],
        [ids.flow_key(s) for s in survey_ids],
        [ids.flow_id(s) for s in survey_ids],
    ):
        assert len(set(family)) == len(family)
