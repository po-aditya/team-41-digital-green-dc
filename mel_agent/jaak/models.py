"""Pydantic v2 models for the JAAK core engine (Req 1.1, 1.3, 20.1).

The models are written by hand and mirror the JSON Schemas in
``data/participant-pack/json/schemas``. The JSON Schema stays authoritative:
every Boundary runs it first, and a document must also pass the model.

Agreement rules used here (so both validators accept and reject the same input):

* strict typing, no coercion (``"5"`` is not an integer, ``True`` is not an integer);
* an integer-valued float such as ``3.0`` counts as an integer, as in JSON Schema;
* patterns use Python ``re.search``, the same engine as ``jsonschema``, so edge
  cases such as ``$`` before a trailing newline behave identically;
* optional keys are not nullable: an explicit ``null`` is rejected unless the
  schema allows it;
* ``format`` keywords are annotations only, as in the shipped validator.

Validation messages carry only fixed keyword reasons. They never include the
offending value, and ``hide_input_in_errors`` keeps values out of Pydantic's own
error text.
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, ClassVar, Literal, Optional, Union

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# --------------------------------------------------------------------------- #
# Shared building blocks
# --------------------------------------------------------------------------- #

SUPPORTED_LANGUAGES = ("hi-IN", "en-IN")

_SURVEY_ID = r"^S-[0-9]{5,10}$"
_HANDOFF_ID = r"^H-[0-9]{5,10}$"
_LANG_TAG = r"^[a-z]{2,3}-[A-Z]{2}$"
_ITEM_ID = r"^[a-z][a-z0-9_]{1,63}$"
_OPTION_VALUE = r"^[a-z0-9][a-z0-9_]{0,63}$"
_IST_TIME = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30$"
_IST_TIME_FRAC = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+05:30$"
_HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
_FLOW_KEY = r"^[a-z][a-z0-9_]{1,63}$"
_ORG_ID = r"^[A-Za-z0-9._-]{1,64}$"
_CAP_KEY = r"^mel:farmer:.{1,64}$"
_COUNTRY = r"^[A-Z]{2}$"
_ASSET_NAME = r"^[a-z][a-z ()-]*$"


def _pattern(regex: str) -> AfterValidator:
    compiled = re.compile(regex)

    def check(value: str) -> str:
        if compiled.search(value) is None:
            raise ValueError("pattern")
        return value

    return AfterValidator(check)


def _json_int(value: Any) -> Any:
    """JSON Schema ``integer``: an integer-valued float is an integer."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _unique(values: list) -> list:
    if len(set(values)) != len(values):
        raise ValueError("uniqueItems")
    return values


JsonInt = Annotated[int, BeforeValidator(_json_int)]
Int0to100 = Annotated[int, BeforeValidator(_json_int), Field(ge=0, le=100)]
Int1to100 = Annotated[int, BeforeValidator(_json_int), Field(ge=1, le=100)]

SurveyId = Annotated[str, _pattern(_SURVEY_ID)]
LangTag = Annotated[str, _pattern(_LANG_TAG)]
ItemId = Annotated[str, _pattern(_ITEM_ID)]
OptionValue = Annotated[str, _pattern(_OPTION_VALUE)]
IstTime = Annotated[str, _pattern(_IST_TIME)]
Id64 = Annotated[str, Field(min_length=1, max_length=64)]
UniqueId64List = Annotated[list[Id64], AfterValidator(_unique)]

FollowUpReason = Literal[
    "advice_did_not_work",
    "crop_or_animal_damaged",
    "could_not_get_input",
    "could_not_reach_expert",
]
Channel = Literal["app", "web", "whatsapp", "telegram", "voice"]
ItemType = Literal["survey-single-select", "survey-confirm", "survey-scale"]


class _Base(BaseModel):
    """Strict, closed model. ``_non_nullable`` lists optional keys that must not be null."""

    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    _non_nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in cls._non_nullable:
                if key in data and data[key] is None:
                    raise ValueError("type")
        return data


# --------------------------------------------------------------------------- #
# survey.schema.json
# --------------------------------------------------------------------------- #


class SendWindow(_Base):
    not_before: IstTime
    not_after: IstTime


class Option(_Base):
    _non_nullable = frozenset({"follow_up"})

    value: OptionValue
    label: Annotated[str, Field(min_length=1, max_length=20)]
    follow_up: Optional[FollowUpReason] = None


class Item(_Base):
    _non_nullable = frozenset(
        {"options", "scale_min", "scale_max", "follow_up_at_or_below", "follow_up_reason"}
    )

    item_id: ItemId
    type: ItemType
    prompt: Annotated[str, Field(min_length=1, max_length=400)]
    options: Optional[Annotated[list[Option], Field(min_length=2, max_length=10)]] = None
    scale_min: Optional[Int0to100] = None
    scale_max: Optional[Int1to100] = None
    follow_up_at_or_below: Optional[Int0to100] = None
    follow_up_reason: Optional[FollowUpReason] = None

    @model_validator(mode="after")
    def _type_rules(self) -> "Item":
        if self.type == "survey-scale":
            if self.scale_min is None or self.scale_max is None:
                raise ValueError("required")
            if self.options is not None:
                raise ValueError("not")
        else:
            if self.options is None:
                raise ValueError("required")
            if (
                self.scale_min is not None
                or self.scale_max is not None
                or self.follow_up_at_or_below is not None
            ):
                raise ValueError("not")
        if self.type == "survey-confirm" and self.options is not None and len(self.options) > 2:
            raise ValueError("maxItems")
        if self.follow_up_at_or_below is not None and self.follow_up_reason is None:
            raise ValueError("required")
        return self


class SelfEval(_Base):
    _non_nullable = frozenset(
        {"schema_valid", "relevance_score", "gives_new_advice", "asks_personal_info"}
    )

    schema_valid: Optional[bool] = None
    relevance_score: Optional[Annotated[float, Field(ge=0, le=1)]] = None
    gives_new_advice: Optional[bool] = None
    asks_personal_info: Optional[bool] = None


class Survey(_Base):
    _non_nullable = frozenset({"self_eval"})

    survey_id: SurveyId
    farmer_id: Id64
    source_insight_ids: Annotated[UniqueId64List, Field(min_length=1, max_length=5)]
    language: LangTag
    send_window: SendWindow
    items: Annotated[list[Item], Field(min_length=1, max_length=3)]
    rationale: Annotated[str, Field(min_length=1, max_length=400)]
    self_eval: Optional[SelfEval] = None


# --------------------------------------------------------------------------- #
# response.schema.json
# --------------------------------------------------------------------------- #

FailureCode = Optional[
    Literal[
        "window_expired",
        "farmer_declined",
        "farmer_opted_out",
        "push_token_invalid",
        "client_cannot_render",
        "wa_session_window_closed",
        "wa_undelivered",
        "tg_bot_blocked",
        "voice_no_answer",
        "voice_busy",
        "voice_call_dropped",
        "free_text_instead_of_choice",
        "keypad_out_of_range",
        "speech_not_understood",
        "survey_closed",
        "survey_replaced",
        "duplicate_answer",
        "identity_mismatch",
        "sheet_dismissed",
        "push_not_opened",
    ]
]
ResponseStatus = Literal[
    "completed",
    "partial",
    "negative_outcome",
    "expired",
    "declined",
    "delivery_failed",
    "invalid_input",
    "stale",
    "duplicate",
    "identity_mismatch",
]
SheetOutcome = Optional[
    Literal["finished", "closed_partway", "interrupted", "dismissed", "never_opened"]
]
ItemResult = Literal["answered", "skipped", "invalid", "not_reached", "discarded"]
InputKind = Optional[
    Literal[
        "sheet_tap", "button_reply", "list_reply", "callback_data", "keypad", "speech", "free_text"
    ]
]
RetryDecision = Literal["none", "retry_same_channel", "fall_back_to_next_channel", "give_up"]


class ItemRecord(_Base):
    item_id: ItemId
    item_type: ItemType
    result: ItemResult
    value: Union[str, JsonInt, None]
    raw_input: Optional[Annotated[str, Field(max_length=256)]]
    input_kind: InputKind
    attempts: Annotated[int, BeforeValidator(_json_int), Field(ge=0, le=5)]


class Timestamps(_Base):
    sent: Optional[IstTime]
    delivered: Optional[IstTime]
    opened: Optional[IstTime]
    answered: Optional[IstTime]


class FarmerChatReply(_Base):
    http_status: JsonInt
    outcome: Literal["accepted", "duplicate", "unknown_flow", "invalid_answer"]

    @field_validator("http_status")
    @classmethod
    def _status_enum(cls, value: int) -> int:
        if value not in (200, 201, 404, 422):
            raise ValueError("enum")
        return value


_AnswerValue = Annotated[
    Union[OptionValue, Int0to100], Field(union_mode="left_to_right")
]
_AnswerKey = Annotated[str, _pattern(_ITEM_ID)]


class ResponseRecord(_Base):
    _non_nullable = frozenset({"question_type"})

    response_key: Id64
    survey_id: SurveyId
    farmer_id: Id64
    source_insight_ids: Annotated[UniqueId64List, Field(min_length=1)]
    channel: Channel
    language: LangTag
    question_type: Optional[Literal["survey-single-select", "survey-scale", "survey-confirm"]] = None
    status: ResponseStatus
    failure_code: FailureCode
    sheet_outcome: SheetOutcome
    answers: Annotated[dict[_AnswerKey, _AnswerValue], Field(max_length=3)]
    items: Annotated[list[ItemRecord], Field(min_length=1, max_length=3)]
    complete: bool
    delivery_attempt: Annotated[int, BeforeValidator(_json_int), Field(ge=1, le=5)]
    timestamps: Timestamps
    recorded_at: IstTime
    answered_by: Optional[Annotated[str, Field(max_length=64)]]
    raw_event: Optional[Annotated[str, Field(max_length=256)]]
    retry_decision: RetryDecision
    retry_after_minutes: Optional[Annotated[int, BeforeValidator(_json_int), Field(ge=0, le=10080)]]
    counts_toward_cap: bool
    farmerchat_reply: Optional[FarmerChatReply]
    needs_follow_up: bool
    follow_up_reasons: Annotated[list[FollowUpReason], AfterValidator(_unique)]


# --------------------------------------------------------------------------- #
# insight.schema.json (validation only)
# --------------------------------------------------------------------------- #


class InsightLocation(_Base):
    country: Annotated[str, _pattern(_COUNTRY)]
    state: Annotated[str, Field(min_length=1, max_length=80)]
    district: Annotated[str, Field(min_length=1, max_length=80)]


class InsightAsset(_Base):
    name: Optional[
        Annotated[str, Field(min_length=1, max_length=60), _pattern(_ASSET_NAME)]
    ]
    category: Literal["crop", "livestock", None]
    growth_stage: Literal[
        "germination",
        "seedling",
        "vegetative",
        "tillering",
        "flowering",
        "fruiting",
        "maturity",
        "harvest",
        "post_harvest",
        "dormant",
        None,
    ]


class InsightVerification(_Base):
    needed: bool
    timing: Literal[
        "none",
        "same_day",
        "next_day",
        "two_to_five_days",
        "three_to_ten_days",
        "seven_to_fourteen_days",
        "seasonal",
    ]
    method: Literal["none", "push", "whatsapp", "ivr_callback", "repeat_photo", "agent_followup"]


class Insight(_Base):
    _non_nullable = frozenset({"quality_flag"})

    insight_id: Id64
    farmer_id: Id64
    conversation_id: Id64
    created_at: Annotated[str, _pattern(_IST_TIME_FRAC)]
    conversation_language: LangTag
    location: InsightLocation
    asset: InsightAsset
    concern: Literal[
        "pest_disease",
        "weather_climate",
        "growth_issue",
        "nutrient_deficiency",
        "variety_selection",
        "soil_health",
        "water_stress",
        "storage_post_harvest",
        "livestock_nutrition",
        "livestock_health",
        "market_price",
        "weed_management",
        "breeding_reproduction",
        "yield_loss",
        None,
    ]
    behavioral_intent: Literal[
        "procedural_guidance",
        "information_seeking",
        "diagnosing",
        "planning",
        "profile_update",
        "exploring_options",
        "symptom_reporting",
        "confirming",
        "decision_making",
        "market_inquiry",
        "following_up",
        "comparing",
        "emergency",
    ]
    decision_episode_type: Literal[
        "decision", "problem_resolution", "general_knowledge", "casual", "exploration", None
    ]
    severity: Literal["low", "medium", "high", "critical", None]
    query_summary: Annotated[str, Field(min_length=1, max_length=400)]
    advice_summary: Annotated[str, Field(min_length=1, max_length=600)]
    resolution_type: Literal[
        "direct_action",
        "generic_information",
        "plan_created",
        "needs_more_context",
        "do_not_act",
        "wait_and_monitor",
        "escalate_to_expert",
    ]
    action_window_days: Optional[Annotated[int, BeforeValidator(_json_int), Field(ge=0, le=180)]]
    verification: InsightVerification
    preferred_channel: Channel
    quality_flag: Optional[Literal["clean", "junk"]] = None


# --------------------------------------------------------------------------- #
# no_survey.schema.json, schedule_handoff.schema.json, bottom_sheet.schema.json
# --------------------------------------------------------------------------- #


class NoSurvey(_Base):
    insight_id: Id64
    farmer_id: Id64
    decision: Literal["no_survey"]
    reason_code: Literal["generic_information", "needs_more_context"]
    reason: Annotated[str, Field(min_length=1, max_length=300)]


class SendHours(_Base):
    from_: Annotated[str, _pattern(_HHMM)] = Field(alias="from")
    to: Annotated[str, _pattern(_HHMM)]

    model_config = ConfigDict(
        strict=True, extra="forbid", hide_input_in_errors=True, populate_by_name=False
    )


class ChannelStep(_Base):
    channel: Channel
    wait_hours: Optional[Annotated[int, BeforeValidator(_json_int), Field(ge=1, le=168)]]


class FrequencyCap(_Base):
    key: Annotated[str, _pattern(_CAP_KEY)]
    max_surveys: Annotated[int, BeforeValidator(_json_int), Field(ge=1, le=7)]
    window_days: Annotated[int, BeforeValidator(_json_int), Field(ge=1, le=90)]
    exempt: bool


class FarmerChatFlow(_Base):
    org_id: Annotated[str, _pattern(_ORG_ID)]
    flow_key: Annotated[str, _pattern(_FLOW_KEY)]
    version: Annotated[int, BeforeValidator(_json_int), Field(ge=1)]
    campaign_id: str  # ``format: uuid`` is an annotation only
    flow_id: str  # ``format: uuid`` is an annotation only


class ScheduleHandoff(_Base):
    handoff_id: Annotated[str, _pattern(_HANDOFF_ID)]
    created_at: IstTime
    survey: Survey
    send_window: SendWindow
    send_hours: SendHours
    channel_order: Annotated[list[ChannelStep], Field(min_length=1, max_length=5)]
    frequency_cap: FrequencyCap
    priority: Literal["high", "normal", "low"]
    expires_at: IstTime
    farmerchat_flow: FarmerChatFlow


class SheetPresentation(_Base):
    type: Literal["bottom_sheet"]
    opens_when: Annotated[
        list[Literal["push_tapped", "next_app_open", "next_web_visit"]],
        Field(min_length=1),
        AfterValidator(_unique),
    ]
    waits_for: Annotated[
        list[Literal["answer_finished_streaming", "no_typing_for_5_seconds", "no_call_in_progress"]],
        Field(min_length=1),
        AfterValidator(_unique),
    ]
    one_question_per_step: Literal[True]
    steps_total: Annotated[int, BeforeValidator(_json_int), Field(ge=1, le=3)]
    can_skip: Literal[True]
    can_close: Literal[True]
    swipe_down_closes: Literal[True]


class SheetOption(_Base):
    label: Annotated[str, Field(min_length=1, max_length=20)]
    answer: _AnswerValue


class SheetStep(_Base):
    step: Annotated[int, BeforeValidator(_json_int), Field(ge=1, le=3)]
    step_label: Annotated[str, Field(min_length=1, max_length=20)]
    item_id: ItemId
    question_type: ItemType
    question: Annotated[str, Field(min_length=1, max_length=400)]
    options: Annotated[list[SheetOption], Field(min_length=2, max_length=10)]


class Sheet(_Base):
    title: Annotated[str, Field(min_length=1, max_length=80)]
    skip_label: Annotated[str, Field(min_length=1, max_length=20)]
    close_label: Annotated[str, Field(min_length=1, max_length=20)]
    thank_you: Annotated[str, Field(min_length=1, max_length=200)]
    steps: Annotated[list[SheetStep], Field(min_length=1, max_length=3)]


class BottomSheet(_Base):
    presentation: SheetPresentation
    sheet: Sheet


# --------------------------------------------------------------------------- #
# Engine inputs (not pack schemas)
# --------------------------------------------------------------------------- #


class FarmerRecord(BaseModel):
    """A farmer row. Unknown columns (state, district, ...) are dropped, never stored."""

    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)

    farmer_id: Id64
    language: Literal["hi-IN", "en-IN"]

    @field_validator("farmer_id")
    @classmethod
    def _has_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("blank")
        return value


_FROZEN = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)


class CallTimes(BaseModel):
    """Optional channel times passed through to ``timestamps`` (timezone-aware)."""

    model_config = _FROZEN

    sent: Optional[datetime] = None
    delivered: Optional[datetime] = None
    opened: Optional[datetime] = None

    @field_validator("sent", "delivered", "opened")
    @classmethod
    def _aware(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.utcoffset() is None:
            raise ValueError("timezone")
        return value


class Timeout(BaseModel):
    model_config = _FROZEN


class ReportFailure(BaseModel):
    """Caller-reported failure. The code is checked against outcome_codes.json by the engine."""

    model_config = _FROZEN

    failure_code: Id64
    reported_farmer_id: Optional[Id64] = None

    @model_validator(mode="after")
    def _identity_payload(self) -> "ReportFailure":
        needs_id = self.failure_code == "identity_mismatch"
        if needs_id != (self.reported_farmer_id is not None):
            raise ValueError("reported_farmer_id")
        return self


class ClosingNotDelivered(BaseModel):
    model_config = _FROZEN


class AnswerReceipt(str, Enum):
    PROCESSED = "processed"
    IGNORED = "ignored"


# --------------------------------------------------------------------------- #
# Turns
# --------------------------------------------------------------------------- #

SegmentSource = Literal["survey_prompt", "option_label", "template", "farmer_name"]
TurnKind = Literal[
    "greeting", "question", "reask", "repeat", "advice_decline", "reprompt", "closing"
]


class Segment(BaseModel):
    """One piece of Turn text and where it came from (Req 16.1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: SegmentSource
    text: str
    ref: str


class Turn(BaseModel):
    """One thing JAAK says. ``text`` is the assembly of ``segments``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: TurnKind
    language: str
    text: str
    segments: tuple[Segment, ...]
    item_id: Optional[str] = None
    expects_reply: bool
