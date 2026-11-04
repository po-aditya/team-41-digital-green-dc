"""Send-window computation, exactly as rules.json describes it.

Days count from the day of the insight. The window opens at not_before_time
(07:00) and closes at not_after_time (19:00) India time. It never opens on the
day of the advice or before the farmer's action window ends, it is at least
min_width_days wide, and nothing is sent after season_end.

This reproduces all five worked scenarios in the pack. The golden set uses a
different formula; see docs/IMPLEMENTATION_PLAN.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from mel_agent.data.pack import Rules
from mel_agent.time_utils import add_days, format_ist, ist_datetime, parse_ist


class TimingError(ValueError):
    pass


@dataclass(frozen=True)
class SendWindow:
    not_before: datetime
    not_after: datetime
    start_day_offset: int
    end_day_offset: int
    timing: str
    action_window_days: int | None
    clamped_to_season_end: bool

    def to_contract(self) -> dict[str, str]:
        return {"not_before": format_ist(self.not_before), "not_after": format_ist(self.not_after)}

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_contract(), "start_day_offset": self.start_day_offset, "end_day_offset": self.end_day_offset,
                "timing": self.timing, "action_window_days": self.action_window_days,
                "clamped_to_season_end": self.clamped_to_season_end}


@dataclass(frozen=True)
class WindowAfterSeason:
    would_start: date
    season_end: date


@dataclass(frozen=True)
class WindowTruncated:
    """The season end would cut the window below min_width_days.

    rules.json demands both "at least two days wide" and "nothing after 31 March";
    when they cannot both hold we do not send automatically (see IMPLEMENTATION_PLAN)."""

    would_start: date
    would_end: date
    season_end: date
    min_width_days: int


def compute_send_window(insight: dict[str, Any], rules: Rules) -> SendWindow | WindowAfterSeason | WindowTruncated:
    """Deterministic window from created_at, verification.timing and action_window_days.

    Days are calendar days counted from the insight's date in India time (the rules
    say "days count from the day of the insight"), not elapsed hours."""
    created = parse_ist(insight["created_at"]).date()
    verification = insight.get("verification") or {}
    timing = verification.get("timing") or "none"
    awd = insight.get("action_window_days")
    wr = rules.window_rules
    table = rules.send_window_days

    if timing not in table:
        raise TimingError(f"unknown verification.timing value")
    if timing == "none" or table[timing] == "from_action_window":
        base = awd if awd is not None else int(wr["action_window_days_if_null"])
        start = base + int(wr["none_start_after_action_window_days"])
        end = base + int(wr["none_end_after_action_window_days"])
    else:
        start, end = (int(x) for x in table[timing])

    start = max(start, int(wr["earliest_start_day"]))
    if wr.get("start_not_before_action_window_end") and awd is not None:
        start = max(start, int(awd))
    min_width = int(wr["min_width_days"])
    if end - start < min_width:
        end = start + min_width

    season_end = date.fromisoformat(rules.season_end)
    start_day = add_days(created, start)
    end_day = add_days(created, end)
    if start_day > season_end:
        return WindowAfterSeason(would_start=start_day, season_end=season_end)
    clamped = False
    if end_day > season_end:
        if (season_end - start_day).days < min_width:
            return WindowTruncated(would_start=start_day, would_end=end_day, season_end=season_end, min_width_days=min_width)
        end_day = season_end
        clamped = True
    return SendWindow(
        not_before=ist_datetime(start_day, wr["not_before_time"]),
        not_after=ist_datetime(end_day, wr["not_after_time"]),
        start_day_offset=start, end_day_offset=(end_day - created).days, timing=timing,
        action_window_days=awd, clamped_to_season_end=clamped,
    )
