"""Survey-generation interface and shared helpers.

A generator turns an eligible insight (plus its computed send window) into a
schema-valid Survey in the farmer's language. Two implementations exist:
  * FakeSurveyGenerator   - deterministic templates, no network. For tests/CI.
  * BedrockSurveyGenerator - real Amazon Bedrock inference.
Both satisfy the SurveyGenerator Protocol so callers never depend on which is
used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from . import ids
from .models import Insight, SelfEval, Survey
from .timing import Window
from .validate import validate

# The only follow_up reasons the survey schema allows.
FOLLOW_UP_REASONS = frozenset(
    {
        "advice_did_not_work",
        "crop_or_animal_damaged",
        "could_not_get_input",
        "could_not_reach_expert",
    }
)

# Answer labels must show whole on a WhatsApp button (schema maxLength 20,
# counted in Unicode code points - so this is safe for Devanagari too).
MAX_LABEL_LEN = 20

# Languages a Milestone-1 generator can actually write questions in.
SUPPORTED_LANGUAGES = ("en-IN", "hi-IN")
DEFAULT_LANGUAGE = "en-IN"


class SurveyValidationError(ValueError):
    """Raised when a generated survey fails the official schema or our checks."""


@runtime_checkable
class SurveyGenerator(Protocol):
    def generate(self, insight: Insight, window: Window) -> Survey:
        """Return a schema-valid Survey for this insight, in its language."""
        ...


def resolve_language(insight: Insight) -> str:
    """The language the survey will ACTUALLY be written in.

    If the insight's conversation_language is one we can author, use it;
    otherwise fall back to the default. The generator must declare this exact
    value as the survey language so the declared language always matches the
    question wording.
    """
    lang = insight.conversation_language
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def new_survey_scaffold(insight: Insight, window: Window, language: str) -> dict:
    """Common survey fields. ``language`` is the resolved authoring language,
    passed in so it is guaranteed to match the question wording."""
    sid = ids.survey_id(insight.insight_id)
    return {
        "survey_id": sid,
        "farmer_id": insight.farmer_id,
        "source_insight_ids": [insight.insight_id],
        "language": language,
        "send_window": {
            "not_before": window.not_before_iso(),
            "not_after": window.not_after_iso(),
        },
    }


def validate_label(label: str) -> str:
    """Return the label unchanged if valid; raise if empty or too long.

    We never truncate - truncating would silently corrupt Hindi text and could
    change an answer's meaning.
    """
    if not label or len(label) > MAX_LABEL_LEN:
        raise SurveyValidationError(
            f"option label must be 1..{MAX_LABEL_LEN} chars, got {len(label)}: {label!r}"
        )
    return label


def validate_follow_up(code: str | None) -> str | None:
    """Return the code if it is a permitted enum value or None; raise otherwise."""
    if code is None:
        return None
    if code not in FOLLOW_UP_REASONS:
        raise SurveyValidationError(f"follow_up {code!r} is not an allowed reason")
    return code


# --------------------------------------------------------------------------
# Lightweight safety audit.
#
# This is a WEAK heuristic. It does NOT prove a survey is safe or high quality;
# it only raises review flags. Design notes:
#   * We scan the WHOLE prompt for new-advice / personal-info patterns. We do
#     NOT exempt a question just because it opens with "Did you ..." - a prompt
#     can start as a verification and still smuggle advice later
#     ("Did you spray? You should apply more urea next week.").
#   * The advice patterns are anchored imperative/future phrases that do not
#     occur in legitimate past-tense verification ("did you apply ...?"), so
#     normal follow-up questions are not flagged.
#   * We never emit a fabricated relevance score - relevance is left unknown
#     for a human/eval step.
# --------------------------------------------------------------------------

_ADVICE_PATTERNS_EN = (
    "you should", "you must", "please apply", "please spray", "please use",
    "we recommend", "it is best to", "make sure to", "try applying", "start using",
    "next time apply", "you can apply", "you need to apply",
)
_ADVICE_PATTERNS_HI = (
    "आपको चाहिए", "कर लें", "कर लीजिए", "लगा लें", "छिड़काव कर", "इस्तेमाल कर", "सलाह है कि",
)
_PERSONAL_PATTERNS = (
    "your name", "phone number", "mobile number", "aadhaar", "aadhar", "address",
    "आपका नाम", "फ़ोन नंबर", "मोबाइल नंबर", "आधार", "पता",
)


@dataclass
class SafetyAudit:
    """Outcome of the lightweight safety check. Flags, not guarantees."""

    gives_new_advice: bool
    asks_personal_info: bool
    review_required: bool
    flags: list[str] = field(default_factory=list)


def audit_survey_safety(survey: Survey) -> SafetyAudit:
    """Flag suspicious wording anywhere in any prompt. Never asserts safety."""
    flags: list[str] = []
    gives_new_advice = False
    asks_personal_info = False

    for item in survey.items:
        prompt = item.prompt.strip()
        low = prompt.lower()

        if any(p in low for p in _ADVICE_PATTERNS_EN) or any(
            p in prompt for p in _ADVICE_PATTERNS_HI
        ):
            gives_new_advice = True
            flags.append(f"possible new advice in {item.item_id}: {prompt[:60]!r}")

        if any(p in low for p in _PERSONAL_PATTERNS) or any(
            p in prompt for p in _PERSONAL_PATTERNS
        ):
            asks_personal_info = True
            flags.append(f"possible personal-info request in {item.item_id}")

    review_required = gives_new_advice or asks_personal_info
    return SafetyAudit(
        gives_new_advice=gives_new_advice,
        asks_personal_info=asks_personal_info,
        review_required=review_required,
        flags=flags,
    )


def self_eval_from_audit(audit: SafetyAudit) -> SelfEval:
    """Build a SelfEval from the audit. relevance_score stays None (unknown):
    we do not fabricate a quality number. SelfEval.dump() omits None, which the
    official schema accepts (it rejects an explicit null relevance_score)."""
    return SelfEval(
        schema_valid=True,
        relevance_score=None,
        gives_new_advice=audit.gives_new_advice,
        asks_personal_info=audit.asks_personal_info,
    )


def ensure_schema_valid(survey: Survey) -> Survey:
    """Validate against the official survey schema; raise on failure."""
    errors = validate("survey", survey.dump())
    if errors:
        raise SurveyValidationError(
            "generated survey failed survey.schema.json: " + "; ".join(errors[:5])
        )
    return survey


def finalize_survey(survey: Survey, *, reject_on_review: bool = True) -> Survey:
    """Run schema validation + safety audit and attach an honest self_eval.

    Raises SurveyValidationError if the survey fails the schema, or (when
    reject_on_review) if the safety audit flags it for review. This is the one
    gate every generator passes its output through before returning.
    """
    ensure_schema_valid(survey)
    audit = audit_survey_safety(survey)
    survey.self_eval = self_eval_from_audit(audit)
    if reject_on_review and audit.review_required:
        raise SurveyValidationError(
            "survey flagged for human review: " + "; ".join(audit.flags[:5])
        )
    return survey
