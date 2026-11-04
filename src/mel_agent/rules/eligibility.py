"""Survey / no-survey decision with explicit precedence (R0..R8).

The decision uses only record content, the supplied rules and the crop
calendar. ``quality_flag`` is never read here. The golden set's own labels are
never consulted. See docs/IMPLEMENTATION_PLAN.md for how R1..R8 were derived.

Precedence (first match wins):
  R0  data integrity (schema, farmer registry, unknown resolution)      -> quarantined
  R2  severity critical, even when other fields look like junk           -> human review
  R1  no agricultural substance (junk / unreadable / incoherent text)    -> no survey
  R3  generic_information          R4 needs_more_context                 -> no survey
  R5  actionable but verification not needed                             -> no survey
  R6  window after the season, or truncated below the minimum width      -> no survey
  R7  window after the crop's calendar end                               -> no survey
  R8  survey

A critical record is routed to a human before any junk test: a contradictory
record (critical + casual) is more likely a classifier error than small talk,
and the cost of a missed emergency is far higher than the cost of one review.

Internal reasons are richer than the external no_survey contract allows, so
each decision carries both: ``internal_reason`` (for reports, evaluation and
the human-intervention queue) and ``external_reason_code`` (one of the two
values no_survey.schema.json permits).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from mel_agent.data.pack import Rules
from mel_agent.rules.timing import SendWindow, WindowAfterSeason, WindowTruncated, compute_send_window


class Outcome(StrEnum):
    SURVEY = "survey"
    NO_SURVEY = "no_survey"
    QUARANTINED = "quarantined"


class Reason(StrEnum):
    # R0: never reaches the rules proper
    SCHEMA_INVALID = "schema_invalid"
    UNKNOWN_FARMER = "unknown_farmer"
    UNKNOWN_RESOLUTION = "unknown_resolution_type"
    # R1..R7
    JUNK_INSIGHT = "junk_insight"
    CRITICAL_NEEDS_HUMAN_CALL = "critical_needs_human_call"
    NOTHING_TO_VERIFY = "nothing_to_verify"
    WAITING_FOR_DETAILS = "waiting_for_details"
    NO_CHECK_NEEDED = "no_check_needed"
    WINDOW_AFTER_SEASON = "window_after_season"
    WINDOW_TRUNCATED_BY_SEASON_END = "window_truncated_by_season_end"
    CROP_ALREADY_HARVESTED = "crop_already_harvested"
    # R8
    SURVEY = "survey"


# External contract: no_survey.schema.json allows only these two codes.
EXTERNAL_CODE: dict[Reason, str | None] = {
    Reason.JUNK_INSIGHT: "generic_information",
    Reason.CRITICAL_NEEDS_HUMAN_CALL: "needs_more_context",
    Reason.NOTHING_TO_VERIFY: "generic_information",
    Reason.WAITING_FOR_DETAILS: "needs_more_context",
    Reason.NO_CHECK_NEEDED: "generic_information",
    Reason.WINDOW_AFTER_SEASON: "generic_information",
    Reason.WINDOW_TRUNCATED_BY_SEASON_END: "generic_information",
    Reason.CROP_ALREADY_HARVESTED: "generic_information",
}

RULE_OF: dict[Reason, str] = {
    Reason.SCHEMA_INVALID: "R0", Reason.UNKNOWN_FARMER: "R0", Reason.UNKNOWN_RESOLUTION: "R0",
    Reason.JUNK_INSIGHT: "R1", Reason.CRITICAL_NEEDS_HUMAN_CALL: "R2", Reason.NOTHING_TO_VERIFY: "R3",
    Reason.WAITING_FOR_DETAILS: "R4", Reason.NO_CHECK_NEEDED: "R5", Reason.WINDOW_AFTER_SEASON: "R6",
    Reason.WINDOW_TRUNCATED_BY_SEASON_END: "R6", Reason.CROP_ALREADY_HARVESTED: "R7", Reason.SURVEY: "R8",
}

REASON_TEXT: dict[Reason, str] = {
    Reason.SCHEMA_INVALID: "The insight fails insight.schema.json and was quarantined.",
    Reason.UNKNOWN_FARMER: "The insight names a farmer who is not in the farmer registry.",
    Reason.UNKNOWN_RESOLUTION: "The resolution type is not covered by rules.json.",
    Reason.JUNK_INSIGHT: "No agricultural question or advice was recorded (greeting, thanks, off-topic or unreadable message), so there is nothing to follow up.",
    Reason.CRITICAL_NEEDS_HUMAN_CALL: "Severity is critical. The farmer should get a human call, not an automated survey; routed to the human-intervention queue.",
    Reason.NOTHING_TO_VERIFY: "Only general information was given. No action was advised, so there is no advice to check on.",
    Reason.WAITING_FOR_DETAILS: "No advice was given yet; FarmerChat is still waiting for details from the farmer.",
    Reason.NO_CHECK_NEEDED: "Advice was given but the insight extractor marked it as not needing verification.",
    Reason.WINDOW_AFTER_SEASON: "The earliest send date falls after the end of the rabi season, so no survey can be sent in time.",
    Reason.WINDOW_TRUNCATED_BY_SEASON_END: "The season ends before the send window could reach its minimum width; the rules for width and season end conflict here, so nothing is sent automatically.",
    Reason.CROP_ALREADY_HARVESTED: "By the time the survey could be sent the crop calendar says this crop's season is over.",
}


@dataclass
class Decision:
    insight_id: str
    farmer_id: str | None
    outcome: Outcome
    reason: Reason
    rule: str
    external_reason_code: str | None
    reason_text: str
    send_window: SendWindow | None = None
    details: dict[str, Any] = field(default_factory=dict)
    needs_human: bool = False

    @property
    def survey(self) -> bool:
        return self.outcome is Outcome.SURVEY

    def to_no_survey_contract(self) -> dict[str, Any]:
        """The external no_survey document (validates against no_survey.schema.json)."""
        if self.outcome is not Outcome.NO_SURVEY:
            raise ValueError("only no_survey decisions have a no_survey document")
        return {
            "insight_id": self.insight_id, "farmer_id": self.farmer_id or "unknown", "decision": "no_survey",
            "reason_code": self.external_reason_code, "reason": f"[{self.reason}] {self.reason_text}"[:300],
        }

    def to_record(self) -> dict[str, Any]:
        return {
            "insight_id": self.insight_id, "farmer_id": self.farmer_id, "decision": self.outcome.value, "rule": self.rule,
            "internal_reason": self.reason.value, "external_reason_code": self.external_reason_code,
            "reason_text": self.reason_text, "details": {**self.details, "needs_human": self.needs_human,
                                                          "send_window": self.send_window.to_dict() if self.send_window else None},
        }


@dataclass
class CropCalendar:
    """Last calendar date per crop, from crop_calendar_bihar_rabi.csv."""

    season_end_by_crop: dict[str, date]

    @classmethod
    def from_rows(cls, rows: list[dict[str, Any]]) -> "CropCalendar":
        ends: dict[str, date] = {}
        for r in rows:
            crop = str(r["crop"]).strip().lower()
            end = date.fromisoformat(str(r["end_date"]))
            if crop not in ends or end > ends[crop]:
                ends[crop] = end
        return cls(ends)

    def last_date(self, crop: str | None) -> date | None:
        if not crop:
            return None
        return self.season_end_by_crop.get(crop.strip().lower())


_CORE_FIELDS = ("resolution_type", "decision_episode_type", "severity", "behavioral_intent")
_WORD = re.compile(r"\w+", re.UNICODE)
_LATIN_WORD = re.compile(r"^[A-Za-z]+$")
_VOWELS = set("aeiouyAEIOUY")


def _latin_gibberish(word: str) -> bool:
    """A Latin-script token no natural language produces: 5+ letters with no vowel, or a run of 6+ consonants."""
    if not _LATIN_WORD.match(word) or len(word) < 5:
        return False
    if not any(ch in _VOWELS for ch in word):
        return True
    run = 0
    for ch in word:
        run = 0 if ch in _VOWELS else run + 1
        if run >= 6:
            return True
    return False


def _unreadable(text: Any) -> bool:
    """A summary that cannot carry an agricultural statement, judged script-neutrally.

    Unreadable: not text, under 8 characters, no alphabetic character in ANY script, fewer than
    two words, fewer than three distinct alphanumerics, or (Latin script only) more than half of
    the words are letter strings no language produces. Devanagari and other scripts are judged
    only on the script-neutral conditions; this is a lexical floor, not a semantic check
    (see docs/CONTRACT_QUESTIONS.md §6 for the limitation)."""
    if not isinstance(text, str):
        return True
    stripped = text.strip()
    if len(stripped) < 8 or not any(ch.isalpha() for ch in stripped):
        return True
    words = [w for w in _WORD.findall(stripped) if any(ch.isalpha() for ch in w)]
    if len(words) < 2:
        return True
    alnum = {c.lower() for c in stripped if c.isalnum()}
    if len(alnum) < 3:
        return True
    latin = [w for w in words if _LATIN_WORD.match(w)]
    if latin and sum(_latin_gibberish(w) for w in latin) * 2 > len(latin):
        return True
    return False


def is_junk(insight: dict[str, Any]) -> tuple[bool, str | None]:
    """Content signature for records with no agricultural substance.

    Checked on the structured fields and the two summaries only, never on quality_flag:
    - a core classification field is null (incomplete extraction),
    - decision_episode_type is 'casual' (small talk, thanks, greetings),
    - neither an asset nor a concern was identified (off-topic or unreadable),
    - the query or advice summary is unreadable (script-neutral lexical floor; Latin-only
      gibberish detection), or the two are identical.
    What this cannot do: judge meaning. Fluent nonsense in any language passes this floor and
    is only caught downstream by the survey content policy and human review.
    """
    for f in _CORE_FIELDS:
        if insight.get(f) is None:
            return True, f"missing_{f}"
    if insight.get("decision_episode_type") == "casual":
        return True, "casual_episode"
    asset = insight.get("asset") or {}
    if asset.get("name") is None and insight.get("concern") is None:
        return True, "no_asset_and_no_concern"
    if _unreadable(insight.get("query_summary")):
        return True, "unreadable_query_summary"
    if _unreadable(insight.get("advice_summary")):
        return True, "unreadable_advice_summary"
    if str(insight.get("query_summary")).strip().lower() == str(insight.get("advice_summary")).strip().lower():
        return True, "query_equals_advice"
    return False, None


def _decision(insight: dict[str, Any], reason: Reason, outcome: Outcome, **details: Any) -> Decision:
    code = EXTERNAL_CODE.get(reason) if outcome is Outcome.NO_SURVEY else None
    return Decision(
        insight_id=str(insight.get("insight_id")), farmer_id=insight.get("farmer_id"), outcome=outcome, reason=reason,
        rule=RULE_OF[reason], external_reason_code=code, reason_text=REASON_TEXT.get(reason, ""),
        details=details, needs_human=(reason is Reason.CRITICAL_NEEDS_HUMAN_CALL),
    )


def decide(insight: dict[str, Any], rules: Rules, calendar: CropCalendar, *, schema_valid: bool = True,
           farmer_known: bool = True) -> Decision:
    """Apply the precedence above and return the first matching rule."""
    # R0: data integrity. These never reach the rules proper.
    if not schema_valid:
        return _decision(insight, Reason.SCHEMA_INVALID, Outcome.QUARANTINED)
    if not farmer_known:
        return _decision(insight, Reason.UNKNOWN_FARMER, Outcome.QUARANTINED)

    junk, signal = is_junk(insight)

    # R2: a critical signal always reaches a human, even on an otherwise junk-looking record.
    if insight.get("severity") == "critical":
        return _decision(insight, Reason.CRITICAL_NEEDS_HUMAN_CALL, Outcome.NO_SURVEY, severity="critical",
                         contradictory_signals=signal if junk else None)

    # R1: junk content.
    if junk:
        return _decision(insight, Reason.JUNK_INSIGHT, Outcome.NO_SURVEY, signal=signal)

    # R3/R4: resolution types the rules mark as no-survey.
    resolution = insight.get("resolution_type")
    surveyable = rules.survey_for_resolution(resolution)
    if surveyable is None:
        return _decision(insight, Reason.UNKNOWN_RESOLUTION, Outcome.QUARANTINED, resolution_type=resolution)
    if not surveyable:
        reason = Reason.WAITING_FOR_DETAILS if resolution == "needs_more_context" else Reason.NOTHING_TO_VERIFY
        return _decision(insight, reason, Outcome.NO_SURVEY, resolution_type=resolution)

    # R5: actionable advice the extractor says needs no check.
    verification = insight.get("verification") or {}
    if not verification.get("needed"):
        return _decision(insight, Reason.NO_CHECK_NEEDED, Outcome.NO_SURVEY, resolution_type=resolution)

    # R6/R7: temporal eligibility.
    window = compute_send_window(insight, rules)
    if isinstance(window, WindowAfterSeason):
        return _decision(insight, Reason.WINDOW_AFTER_SEASON, Outcome.NO_SURVEY,
                         would_start=window.would_start.isoformat(), season_end=window.season_end.isoformat())
    if isinstance(window, WindowTruncated):
        return _decision(insight, Reason.WINDOW_TRUNCATED_BY_SEASON_END, Outcome.NO_SURVEY,
                         would_start=window.would_start.isoformat(), would_end=window.would_end.isoformat(),
                         season_end=window.season_end.isoformat(), min_width_days=window.min_width_days)
    asset = insight.get("asset") or {}
    if asset.get("category") == "crop":
        crop_end = calendar.last_date(asset.get("name"))
        if crop_end is not None and window.not_before.date() > crop_end:
            return _decision(insight, Reason.CROP_ALREADY_HARVESTED, Outcome.NO_SURVEY,
                             crop=asset.get("name"), crop_calendar_end=crop_end.isoformat(), would_start=window.not_before.date().isoformat())

    # R8: survey.
    decision = _decision(insight, Reason.SURVEY, Outcome.SURVEY, resolution_type=resolution, asks=rules.asks_for_resolution(resolution))
    decision.send_window = window
    return decision
