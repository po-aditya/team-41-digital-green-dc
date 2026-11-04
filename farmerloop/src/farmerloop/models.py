"""Shared data models mirroring the participant-pack JSON schemas.

These Pydantic models are the in-code contract between modules. They are a
convenience layer: the authoritative validation gate is the supplied JSON
Schemas, applied via ``farmerloop.validate``. Models stay permissive where the
schema is strict (e.g. we do not re-encode every regex) so that junk data can
be loaded and inspected before it is rejected.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# Enumerations (kept in sync with insight.schema.json).
# --------------------------------------------------------------------------
class ResolutionType(str, Enum):
    DIRECT_ACTION = "direct_action"
    GENERIC_INFORMATION = "generic_information"
    PLAN_CREATED = "plan_created"
    NEEDS_MORE_CONTEXT = "needs_more_context"
    DO_NOT_ACT = "do_not_act"
    WAIT_AND_MONITOR = "wait_and_monitor"
    ESCALATE_TO_EXPERT = "escalate_to_expert"


Channel = Literal["app", "web", "whatsapp", "telegram", "voice"]
Priority = Literal["high", "normal", "low"]
VerificationTiming = Literal[
    "none",
    "same_day",
    "next_day",
    "two_to_five_days",
    "three_to_ten_days",
    "seven_to_fourteen_days",
    "seasonal",
]
VerificationMethod = Literal[
    "none", "push", "whatsapp", "ivr_callback", "repeat_photo", "agent_followup"
]
ItemType = Literal["survey-single-select", "survey-confirm", "survey-scale"]
FollowUpReason = Literal[
    "advice_did_not_work",
    "crop_or_animal_damaged",
    "could_not_get_input",
    "could_not_reach_expert",
]


# --------------------------------------------------------------------------
# Insight (input).
# --------------------------------------------------------------------------
class Location(BaseModel):
    model_config = ConfigDict(extra="allow")
    country: str | None = None
    state: str | None = None
    district: str | None = None


class Asset(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str | None = None
    category: str | None = None
    growth_stage: str | None = None


class Verification(BaseModel):
    model_config = ConfigDict(extra="allow")
    needed: bool = False
    timing: str = "none"
    method: str = "none"


class Insight(BaseModel):
    """One farmer-conversation insight. Permissive so junk rows still load."""

    model_config = ConfigDict(extra="allow")

    insight_id: str
    farmer_id: str | None = None
    conversation_id: str | None = None
    created_at: str | None = None
    conversation_language: str | None = None
    location: Location = Field(default_factory=Location)
    asset: Asset = Field(default_factory=Asset)
    concern: str | None = None
    behavioral_intent: str | None = None
    decision_episode_type: str | None = None
    severity: str | None = None
    query_summary: str | None = None
    advice_summary: str | None = None
    resolution_type: str | None = None
    action_window_days: int | None = None
    verification: Verification = Field(default_factory=Verification)
    preferred_channel: str | None = None
    quality_flag: str | None = None

    @property
    def raw(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# --------------------------------------------------------------------------
# Survey (output of the agent).
# --------------------------------------------------------------------------
class Option(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str
    label: str
    follow_up: FollowUpReason | None = None

    def dump(self) -> dict[str, Any]:
        d: dict[str, Any] = {"value": self.value, "label": self.label}
        if self.follow_up is not None:
            d["follow_up"] = self.follow_up
        return d


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str
    type: ItemType
    prompt: str
    options: list[Option] | None = None
    scale_min: int | None = None
    scale_max: int | None = None
    follow_up_at_or_below: int | None = None
    follow_up_reason: FollowUpReason | None = None

    def dump(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "item_id": self.item_id,
            "type": self.type,
            "prompt": self.prompt,
        }
        if self.type == "survey-scale":
            d["scale_min"] = self.scale_min
            d["scale_max"] = self.scale_max
            if self.follow_up_at_or_below is not None:
                d["follow_up_at_or_below"] = self.follow_up_at_or_below
                d["follow_up_reason"] = self.follow_up_reason
        else:
            d["options"] = [o.dump() for o in (self.options or [])]
        return d


class SendWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    not_before: str
    not_after: str

    def dump(self) -> dict[str, Any]:
        return {"not_before": self.not_before, "not_after": self.not_after}


class SelfEval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_valid: bool | None = None
    relevance_score: float | None = None
    gives_new_advice: bool | None = None
    asks_personal_info: bool | None = None

    def dump(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class Survey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    survey_id: str
    farmer_id: str
    source_insight_ids: list[str]
    language: str
    send_window: SendWindow
    items: list[Item]
    rationale: str
    self_eval: SelfEval | None = None

    def dump(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "survey_id": self.survey_id,
            "farmer_id": self.farmer_id,
            "source_insight_ids": list(self.source_insight_ids),
            "language": self.language,
            "send_window": self.send_window.dump(),
            "items": [i.dump() for i in self.items],
            "rationale": self.rationale,
        }
        if self.self_eval is not None:
            d["self_eval"] = self.self_eval.dump()
        return d


# --------------------------------------------------------------------------
# No-survey (output of the agent). Schema allows only two reason_codes.
# --------------------------------------------------------------------------
NoSurveyReasonCode = Literal["generic_information", "needs_more_context"]


class NoSurvey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    insight_id: str
    farmer_id: str
    decision: Literal["no_survey"] = "no_survey"
    reason_code: NoSurveyReasonCode
    reason: str

    def dump(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
