"""Turn a Decision into the delivered artifact(s), honestly.

For an eligible insight we build survey -> handoff. For an ineligible one we
build a no_survey record IF the true reason has a truthful schema equivalent
AND all required fields are genuinely present; otherwise we refuse to emit a
misleading or fabricated schema-valid record and instead return a documented
ContractGap the caller must handle (log / route to an internal queue). We never
invent a reason code or stub out missing required data to satisfy the schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .decide import Decision
from .models import NoSurvey
from .validate import validate

# India Standard Time (UTC+05:30), fixed offset (India has no DST).
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class ContractGap:
    """An ineligible decision we cannot emit as schema-valid no_survey:
    either the true reason is not representable, the record fails the official
    schema, or required data is missing. Carries the real reason for internal
    handling; NOT schema-valid no_survey output."""

    insight_id: str
    farmer_id: str | None
    internal_reason_code: str
    rule: str
    reason: str


def emit_no_survey(decision: Decision) -> NoSurvey | ContractGap:
    """Build a schema-valid NoSurvey when the reason is truthfully
    representable and all required data is present; otherwise a ContractGap.
    ``decision.survey`` must be False."""
    if decision.survey:
        raise ValueError("emit_no_survey called on an eligible decision")

    def gap(reason: str) -> ContractGap:
        return ContractGap(
            insight_id=decision.insight_id,
            farmer_id=decision.farmer_id,
            internal_reason_code=decision.internal_reason_code,
            rule=decision.rule,
            reason=reason,
        )

    # 1. Reason must be truthfully representable by the schema's two codes.
    if not (decision.schema_representable and decision.schema_reason_code):
        return gap(decision.notes or decision.internal_reason_code)

    # 2. Required data must genuinely exist - do not stub a missing farmer_id.
    if not decision.farmer_id:
        return gap("missing farmer_id; cannot build schema-valid no_survey")

    record = NoSurvey(
        insight_id=decision.insight_id,
        farmer_id=decision.farmer_id,
        reason_code=decision.schema_reason_code,  # a truthful equivalent
        reason=(decision.notes or decision.internal_reason_code)[:300],
    )

    # 3. Validate against the official schema before returning.
    errors = validate("no_survey", record.dump())
    if errors:
        return gap("no_survey failed schema: " + "; ".join(errors[:3]))
    return record


def now_ist(reference: datetime | None = None) -> datetime:
    """Return a timezone-aware IST datetime.

    With no reference, the current time in IST. With a reference: if naive it is
    assumed to be IST; if aware it is converted to IST. Either way the result
    carries the +05:30 offset.
    """
    if reference is None:
        return datetime.now(IST)
    if reference.tzinfo is None:
        return reference.replace(tzinfo=IST)
    return reference.astimezone(IST)
