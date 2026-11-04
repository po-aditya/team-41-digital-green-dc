"""Tests for honest no_survey emission and IST time handling."""

from datetime import datetime, timedelta, timezone

import pytest

from farmerloop.decide import decide
from farmerloop.emit import ContractGap, emit_no_survey, now_ist
from farmerloop.models import NoSurvey
from farmerloop.validate import validate

from tests.helpers import make_insight

IST_DELTA = timedelta(hours=5, minutes=30)


def test_nothing_to_verify_emits_generic_information():
    d = decide(make_insight(resolution_type="generic_information"))
    out = emit_no_survey(d)
    assert isinstance(out, NoSurvey)
    assert out.reason_code == "generic_information"
    assert validate("no_survey", out.dump()) == []


def test_waiting_for_details_emits_needs_more_context():
    d = decide(make_insight(resolution_type="needs_more_context"))
    out = emit_no_survey(d)
    assert isinstance(out, NoSurvey)
    assert out.reason_code == "needs_more_context"
    assert validate("no_survey", out.dump()) == []


@pytest.mark.parametrize(
    "over, internal",
    [
        ({"quality_flag": "junk"}, "junk_insight"),
        ({"severity": "critical"}, "critical_needs_human_call"),
        (
            {"verification": {"needed": False, "timing": "none", "method": "none"}},
            "no_check_needed",
        ),
    ],
)
def test_unrepresentable_reasons_become_contract_gaps(over, internal):
    d = decide(make_insight(**over))
    out = emit_no_survey(d)
    assert isinstance(out, ContractGap)
    # The true reason is preserved, never replaced by a schema stand-in.
    assert out.internal_reason_code == internal


def test_missing_farmer_id_is_not_fabricated():
    d = decide(make_insight(resolution_type="generic_information", farmer_id=None))
    out = emit_no_survey(d)
    assert isinstance(out, ContractGap)
    assert "farmer_id" in out.reason


def test_emit_rejects_eligible_decision():
    with pytest.raises(ValueError):
        emit_no_survey(decide(make_insight()))


def test_now_ist_is_aware_and_ist():
    assert now_ist().utcoffset() == IST_DELTA


def test_now_ist_naive_reference_assumed_ist():
    out = now_ist(datetime(2026, 11, 13, 23, 0))
    assert out.utcoffset() == IST_DELTA
    assert (out.hour, out.minute) == (23, 0)


def test_now_ist_converts_aware_reference():
    out = now_ist(datetime(2026, 11, 13, 17, 30, tzinfo=timezone.utc))
    assert out.utcoffset() == IST_DELTA
    assert (out.day, out.hour, out.minute) == (13, 23, 0)
