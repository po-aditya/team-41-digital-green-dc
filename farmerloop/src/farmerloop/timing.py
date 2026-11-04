"""Send-window math, shared by eligibility (R6) and scheduling.

All clocks are India Standard Time (+05:30). We follow the DOCUMENTED rules in
rules.json and the brief - window opens 07:00, closes 19:00, at least two days
wide, never on the advice day, never before the farmer's action window ends,
nothing after the season end (31 Mar 2027). We deliberately do NOT hardcode the
golden set's observed 09:00 start; discrepancies are reported by the evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .config import IST_OFFSET

SEASON_END = date(2027, 3, 31)

NOT_BEFORE_TIME = "07:00:00"
NOT_AFTER_TIME = "19:00:00"
MIN_WIDTH_DAYS = 2

# Offset in days after the advice day for each verification timing.
# From rules.json send_window_days: [min_days, max_days].
TIMING_DAYS: dict[str, tuple[int, int]] = {
    "same_day": (0, 1),
    "next_day": (1, 2),
    "two_to_five_days": (2, 5),
    "three_to_ten_days": (3, 10),
    "seven_to_fourteen_days": (7, 14),
    "seasonal": (21, 45),
}

# rules.json window_rules for the "none" timing / null action window.
NONE_START_AFTER_ACTION_WINDOW = 1
NONE_END_AFTER_ACTION_WINDOW = 7
ACTION_WINDOW_DAYS_IF_NULL = 2
EARLIEST_START_DAY = 1  # never the advice day (day 0)


def parse_ist_date(created_at: str | None) -> date | None:
    """Parse an insight created_at into its calendar date, or None."""
    if not created_at:
        return None
    try:
        return datetime.fromisoformat(created_at).date()
    except ValueError:
        return None


@dataclass
class Window:
    start: date
    end: date

    def not_before_iso(self) -> str:
        return f"{self.start.isoformat()}T{NOT_BEFORE_TIME}{IST_OFFSET}"

    def not_after_iso(self) -> str:
        return f"{self.end.isoformat()}T{NOT_AFTER_TIME}{IST_OFFSET}"


def _offsets(timing: str, action_window_days: int | None) -> tuple[int, int]:
    """Return (start_offset, end_offset) in days after the advice day."""
    if timing in TIMING_DAYS:
        return TIMING_DAYS[timing]
    # "none" timing: window keyed off the action window length.
    awd = action_window_days if action_window_days is not None else ACTION_WINDOW_DAYS_IF_NULL
    return (awd + NONE_START_AFTER_ACTION_WINDOW, awd + NONE_END_AFTER_ACTION_WINDOW)


def compute_window(
    created_at: str | None,
    timing: str,
    action_window_days: int | None,
) -> Window | None:
    """Compute the send window per the documented rules.

    Returns None when the input date cannot be parsed or no window of the
    required minimum width fits before season end. Eligibility alone does not
    guarantee that a feasible window exists.
    """
    advice_day = parse_ist_date(created_at)
    if advice_day is None:
        return None

    start_off, end_off = _offsets(timing, action_window_days)

    start = advice_day + timedelta(days=start_off)
    end = advice_day + timedelta(days=end_off)

    # Never the advice day or before it.
    earliest = advice_day + timedelta(days=EARLIEST_START_DAY)
    if start < earliest:
        start = earliest

    # Never before the farmer's action window ends.
    if action_window_days is not None:
        action_end = advice_day + timedelta(days=action_window_days)
        if start < action_end:
            start = action_end

    # At least MIN_WIDTH_DAYS wide.
    if (end - start).days < MIN_WIDTH_DAYS:
        end = start + timedelta(days=MIN_WIDTH_DAYS)

    # Nothing is sent after the season ends: clamp the window END to the
    # cutoff. If the start is already at/after the cutoff, or clamping would
    # make the window narrower than the 2-day minimum, the survey is NOT
    # schedulable - return None rather than emit an out-of-season or too-narrow
    # window.
    if start > SEASON_END:
        return None
    if end > SEASON_END:
        end = SEASON_END
    if (end - start).days < MIN_WIDTH_DAYS:
        return None

    return Window(start=start, end=end)


def earliest_possible_start(
    created_at: str | None,
    timing: str,
    action_window_days: int | None,
) -> date | None:
    """The earliest calendar date a follow-up could open. Used by R6.

    This is the start BEFORE the season clamp (which only affects the end), so
    R6's "earliest start is after the season" check is unaffected by the
    end-clamp feasibility logic in compute_window.
    """
    advice_day = parse_ist_date(created_at)
    if advice_day is None:
        return None
    start_off, _ = _offsets(timing, action_window_days)
    start = advice_day + timedelta(days=start_off)
    earliest = advice_day + timedelta(days=EARLIEST_START_DAY)
    if start < earliest:
        start = earliest
    if action_window_days is not None:
        action_end = advice_day + timedelta(days=action_window_days)
        if start < action_end:
            start = action_end
    return start
