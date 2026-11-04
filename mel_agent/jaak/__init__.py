"""JAAK core: deterministic survey conversation engine.

Public API: ``JaakEngine`` with exactly five operations (``start_session``,
``next_turn``, ``submit_answer``, ``submit_event``, ``get_response``), the value
types the operations exchange, and the error classes.
"""
from .engine import JaakEngine
from .errors import (
    ConfigError,
    EventRejected,
    GreetingFailed,
    InputRejected,
    InvalidRequest,
    JaakError,
    LanguageUnavailable,
    NotEnded,
    OutOfOrder,
    RecordInvalid,
    RecordUnavailable,
    SessionFinalised,
    SurveyTextMissing,
    TemplateError,
    TurnsPending,
    UnknownSession,
)
from .models import (
    AnswerReceipt,
    CallTimes,
    ClosingNotDelivered,
    ReportFailure,
    Segment,
    Timeout,
    Turn,
)

__all__ = [
    "JaakEngine",
    "Turn",
    "Segment",
    "CallTimes",
    "Timeout",
    "ReportFailure",
    "ClosingNotDelivered",
    "AnswerReceipt",
    "JaakError",
    "InputRejected",
    "InvalidRequest",
    "LanguageUnavailable",
    "GreetingFailed",
    "SurveyTextMissing",
    "TemplateError",
    "UnknownSession",
    "SessionFinalised",
    "OutOfOrder",
    "NotEnded",
    "TurnsPending",
    "EventRejected",
    "RecordInvalid",
    "RecordUnavailable",
    "ConfigError",
]
