"""Simulated clock shared by the scheduler and broadcaster (Technical doc: "Simulated Clock")."""

from __future__ import annotations

from datetime import datetime, timedelta

from mel_agent.time_utils import IST, format_ist, parse_ist


class SimulatedClock:
    def __init__(self, now: datetime | str) -> None:
        self._now = parse_ist(now) if isinstance(now, str) else now.astimezone(IST)

    @property
    def now(self) -> datetime:
        return self._now

    def iso(self) -> str:
        return format_ist(self._now)

    def advance(self, **kwargs: int) -> datetime:
        self._now = self._now + timedelta(**kwargs)
        return self._now

    def set(self, when: datetime | str) -> datetime:
        self._now = parse_ist(when) if isinstance(when, str) else when.astimezone(IST)
        return self._now
