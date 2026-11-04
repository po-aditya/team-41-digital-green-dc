"""Locate and load the read-only participant pack (rules, outcome codes, data files)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from mel_agent.config import Settings


class PackError(RuntimeError):
    pass


@dataclass(frozen=True)
class PackPaths:
    root: Path

    @property
    def insights_jsonl(self) -> Path:
        return self.root / "data" / "insights.jsonl"

    @property
    def insights_csv(self) -> Path:
        return self.root / "data" / "insights.csv"

    @property
    def farmers_csv(self) -> Path:
        return self.root / "data" / "farmers.csv"

    @property
    def crop_calendar_csv(self) -> Path:
        return self.root / "data" / "crop_calendar_bihar_rabi.csv"

    @property
    def golden_jsonl(self) -> Path:
        return self.root / "data" / "golden_set.jsonl"

    @property
    def rules_json(self) -> Path:
        return self.root / "json" / "rules" / "rules.json"

    @property
    def outcome_codes_json(self) -> Path:
        return self.root / "json" / "rules" / "outcome_codes.json"

    @property
    def schemas_dir(self) -> Path:
        return self.root / "json" / "schemas"

    def require(self) -> "PackPaths":
        missing = [p for p in (self.insights_jsonl, self.farmers_csv, self.crop_calendar_csv, self.rules_json, self.outcome_codes_json) if not p.is_file()]
        if missing:
            raise PackError(f"participant pack incomplete under {self.root}: missing {', '.join(m.name for m in missing)}")
        return self


def pack_paths(settings: Settings) -> PackPaths:
    return PackPaths(Path(settings.participant_pack_dir))


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PackError(f"missing pack file: {path.name}") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackError(f"pack file {path.name} is not valid JSON ({type(exc).__name__})") from None


@lru_cache(maxsize=8)
def _cached_json(path_str: str) -> Any:
    return _load_json(Path(path_str))


class Rules:
    """Typed view over rules.json. Values come from the file, never from code."""

    ACTIONABLE = frozenset({"direct_action", "wait_and_monitor", "do_not_act", "plan_created", "escalate_to_expert"})

    def __init__(self, raw: dict[str, Any]) -> None:
        required = ("survey_by_resolution", "send_window_days", "window_rules", "priority", "channel_by_method",
                    "wait_hours_by_priority", "send_hours", "frequency_cap", "expiry_days_after_window", "farmerchat_flow")
        missing = [k for k in required if k not in raw]
        if missing:
            raise PackError(f"rules.json missing keys: {', '.join(missing)}")
        self.raw = raw

    @classmethod
    def load(cls, paths: PackPaths) -> "Rules":
        return cls(_cached_json(str(paths.rules_json)))

    def survey_for_resolution(self, resolution: str | None) -> bool | None:
        entry = self.raw["survey_by_resolution"].get(resolution or "")
        return None if entry is None else bool(entry["survey"])

    def asks_for_resolution(self, resolution: str) -> str:
        return self.raw["survey_by_resolution"][resolution]["asks"]

    @property
    def send_window_days(self) -> dict[str, Any]:
        return self.raw["send_window_days"]

    @property
    def window_rules(self) -> dict[str, Any]:
        return self.raw["window_rules"]

    @property
    def priority(self) -> dict[str, Any]:
        return self.raw["priority"]

    @property
    def channel_by_method(self) -> dict[str, str | None]:
        return self.raw["channel_by_method"]

    @property
    def wait_hours_by_priority(self) -> dict[str, int]:
        return self.raw["wait_hours_by_priority"]

    @property
    def send_hours(self) -> dict[str, str]:
        return self.raw["send_hours"]

    @property
    def frequency_cap(self) -> dict[str, Any]:
        return self.raw["frequency_cap"]

    @property
    def expiry_days_after_window(self) -> int:
        return int(self.raw["expiry_days_after_window"])

    @property
    def farmerchat_flow(self) -> dict[str, Any]:
        return self.raw["farmerchat_flow"]

    @property
    def season_end(self) -> str:
        return self.raw["window_rules"]["season_end"]


class OutcomeCodes:
    """Typed view over outcome_codes.json."""

    def __init__(self, raw: dict[str, Any]) -> None:
        for key in ("success", "failures", "sheet_cases"):
            if key not in raw:
                raise PackError(f"outcome_codes.json missing '{key}'")
        self.raw = raw

    @classmethod
    def load(cls, paths: PackPaths) -> "OutcomeCodes":
        return cls(_cached_json(str(paths.outcome_codes_json)))

    def failure(self, code: str) -> dict[str, Any]:
        return self.raw["failures"][code]

    def failures_for_channel(self, channel: str) -> list[str]:
        return sorted(code for code, spec in self.raw["failures"].items() if channel in spec["channels"])

    def success(self, status: str) -> dict[str, Any]:
        return self.raw["success"][status]

    def sheet_case(self, case: str) -> dict[str, Any]:
        return self.raw["sheet_cases"][case]
