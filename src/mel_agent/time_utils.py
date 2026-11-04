"""India Standard Time helpers.

Every timestamp in the contract is an ISO-8601 string with a fixed +05:30
offset and no fractional seconds (``survey.schema.json#/$defs/ist_time``).
Nothing here reads the wall clock: callers pass explicit reference times, so
the synthetic November 2026 to March 2027 season can be replayed at any date.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name="IST")
_IST_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+05:30$")


class TimeFormatError(ValueError):
    pass


def parse_ist(value: str) -> datetime:
    """Parse a contract timestamp. Rejects anything not in the +05:30 form."""
    if not isinstance(value, str) or not _IST_RE.match(value):
        raise TimeFormatError("timestamp must look like YYYY-MM-DDTHH:MM:SS+05:30")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TimeFormatError(f"timestamp is not a real date-time ({exc})") from None
    return parsed.astimezone(IST)


def format_ist(value: datetime) -> str:
    """Format as the contract requires: seconds precision, literal +05:30."""
    if value.tzinfo is None:
        raise TimeFormatError("naive datetimes are not allowed; attach a timezone")
    return value.astimezone(IST).replace(microsecond=0).isoformat()


def ist_datetime(day: date, hhmm: str) -> datetime:
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return datetime.combine(day, time(hours, minutes), tzinfo=IST)


def parse_hhmm(hhmm: str) -> time:
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return time(hours, minutes)


def add_days(day: date, days: int) -> date:
    return day + timedelta(days=days)
