from datetime import date, datetime, timezone

import pytest

from mel_agent.time_utils import IST, TimeFormatError, add_days, format_ist, ist_datetime, parse_hhmm, parse_ist


def test_parse_and_format_round_trip():
    s = "2026-12-04T09:12:00+05:30"
    dt = parse_ist(s)
    assert dt.tzinfo is not None and dt.utcoffset().total_seconds() == 5.5 * 3600
    assert format_ist(dt) == s


@pytest.mark.parametrize("bad", ["2026-12-04T09:12:00Z", "2026-12-04T09:12:00+00:00", "2026-12-04", "", None, "2026-13-45T09:12:00+05:30", 123])
def test_parse_rejects_non_ist_or_impossible(bad):
    with pytest.raises(TimeFormatError):
        parse_ist(bad)


def test_format_requires_timezone_and_converts_utc():
    with pytest.raises(TimeFormatError):
        format_ist(datetime(2026, 12, 4, 9, 12))
    assert format_ist(datetime(2026, 12, 4, 3, 42, tzinfo=timezone.utc)) == "2026-12-04T09:12:00+05:30"


def test_helpers():
    assert ist_datetime(date(2026, 12, 6), "07:00") == datetime(2026, 12, 6, 7, 0, tzinfo=IST)
    assert parse_hhmm("19:00").hour == 19
    assert add_days(date(2026, 12, 31), 1) == date(2027, 1, 1)
