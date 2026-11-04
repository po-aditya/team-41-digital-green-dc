"""Eligibility decision: should an insight get a follow-up survey?

Two design rules, per project decisions:

1. REASONS ARE NOT LAUNDERED, BUT TRUTHFUL EQUIVALENTS ARE ALLOWED. Each
   decision carries its TRUE internal reason code (mirroring the golden set's
   R1-R8 taxonomy). The supplied ``no_survey.schema.json`` can only express
   ``generic_information`` and ``needs_more_context``. Where an internal reason
   is semantically the SAME thing as a schema code, we map it truthfully
   (``nothing_to_verify`` == ``generic_information``; ``waiting_for_details``
   == ``needs_more_context``). Where it is NOT the same meaning, we refuse to
   substitute: ``schema_representable`` is False, ``schema_reason_code`` is
   None, and the caller must handle the documented contract gap. See
   docs/DECISIONS.md.

2. SEASON CHECK USES THE REAL EARLIEST FOLLOW-UP DATE, not the insight date.
   R6 compares the computed earliest window start against the season end.

The decision is pure Python - deterministic and scorable against
golden_set.jsonl.

Rule precedence (derived from the golden set):
    R1 junk  ->  R2 critical  ->  R5 no-verification-needed
    ->  R3/R4 non-actionable resolution  ->  R6 window-after-season  ->  R8 survey.

NOTE on R7 (crop_already_harvested): the golden set contains exactly one R7
case (G-0136) which is NOT distinguishable from legitimate R8 post-harvest
surveys by any structured field - post_harvest/harvest/dormant stages and
stored-produce queries all appear in genuine R8 surveys. R7 depends on whether
the SPECIFIC advice is still verifiable, which needs semantics this
deterministic gate does not have. We therefore do NOT implement a structural
R7 rejection (it would wrongly reject ~9 valid R8 surveys to catch 1 R7). This
is a documented limitation; see docs/DECISIONS.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Insight
from .timing import SEASON_END, earliest_possible_start

# Resolution types that warrant a follow-up survey (rules.json).
SURVEY_RESOLUTIONS = {
    "direct_action",
    "wait_and_monitor",
    "do_not_act",
    "plan_created",
    "escalate_to_expert",
}

# Internal rule codes mirror the golden-set taxonomy.
RULE_JUNK = "R1"
RULE_CRITICAL_HUMAN = "R2"
RULE_NOTHING_TO_VERIFY = "R3"
RULE_WAITING_FOR_DETAILS = "R4"
RULE_NO_CHECK_NEEDED = "R5"
RULE_WINDOW_AFTER_SEASON = "R6"
RULE_CROP_HARVESTED = "R7"  # defined for completeness; not emitted by this gate.
RULE_SURVEY = "R8"

# Internal reason code -> rule code.
INTERNAL_REASON_RULE = {
    "junk_insight": RULE_JUNK,
    "critical_needs_human_call": RULE_CRITICAL_HUMAN,
    "nothing_to_verify": RULE_NOTHING_TO_VERIFY,
    "waiting_for_details": RULE_WAITING_FOR_DETAILS,
    "no_check_needed": RULE_NO_CHECK_NEEDED,
    "window_after_season": RULE_WINDOW_AFTER_SEASON,
    "crop_already_harvested": RULE_CROP_HARVESTED,
}

# Truthful semantic equivalences: internal reason -> schema reason code.
# These are the SAME meaning, not a stand-in. Any internal reason absent here
# genuinely cannot be represented by the supplied no_survey schema.
TRUTHFUL_SCHEMA_EQUIVALENT = {
    "nothing_to_verify": "generic_information",
    "waiting_for_details": "needs_more_context",
    # A reason that is itself already a schema code maps to itself.
    "generic_information": "generic_information",
    "needs_more_context": "needs_more_context",
}


@dataclass
class Decision:
    """Result of the eligibility gate.

    ``survey`` says whether a survey should be built. ``rule`` and
    ``internal_reason_code`` carry the true, rich taxonomy. ``schema_reason_code``
    is set ONLY when the true reason has a truthful schema equivalent; otherwise
    it is None and ``schema_representable`` is False, signalling a documented
    contract gap. ``notes`` explains the call.
    """

    insight_id: str
    farmer_id: str | None
    survey: bool
    rule: str
    internal_reason_code: str
    schema_representable: bool = True
    schema_reason_code: str | None = None
    notes: str = ""
    warnings: list[str] = field(default_factory=list)


def decide(insight: Insight, *, schema_ok: bool = True) -> Decision:
    """Decide survey vs no-survey for one insight.

    ``schema_ok`` is whether the raw insight passed insight.schema.json. A row
    that fails the schema is treated as junk regardless of its quality_flag.
    """

    iid = insight.insight_id
    fid = insight.farmer_id
    warnings: list[str] = []

    def no(internal: str, note: str) -> Decision:
        schema_code = TRUTHFUL_SCHEMA_EQUIVALENT.get(internal)
        return Decision(
            insight_id=iid,
            farmer_id=fid,
            survey=False,
            rule=INTERNAL_REASON_RULE[internal],
            internal_reason_code=internal,
            schema_representable=schema_code is not None,
            schema_reason_code=schema_code,
            notes=note,
            warnings=warnings,
        )

    # R1 - junk. Broken-on-purpose rows and anything that fails the schema.
    if insight.quality_flag == "junk" or not schema_ok:
        return no("junk_insight",
                  "Insight is marked junk or fails the insight schema; not actionable.")

    # R2 - critical severity goes to a human, not an automated tap survey.
    # (In the golden set, critical severity always blocks a survey, regardless
    # of resolution_type or behavioral_intent.)
    if insight.severity == "critical":
        return no("critical_needs_human_call",
                  "Critical severity: needs a human call/expert, not an automated survey.")

    # R5 - advice that explicitly needs no verification.
    # (In the golden set, verification.needed == false always blocks a survey.)
    if not insight.verification.needed:
        return no("no_check_needed",
                  "Advice flagged as needing no verification; nothing to follow up.")

    res = insight.resolution_type

    # R3 - only general information was given.
    if res == "generic_information":
        return no("nothing_to_verify",
                  "Only general information was given; there is no advice to verify.")
    # R4 - conversation still open, no advice finalised.
    if res == "needs_more_context":
        return no("waiting_for_details",
                  "Conversation is still open; no advice was finalised to follow up.")

    # Unknown / missing resolution - not an actionable, verifiable outcome.
    if res not in SURVEY_RESOLUTIONS:
        warnings.append(f"unexpected resolution_type={res!r}")
        return no("nothing_to_verify",
                  f"Resolution {res!r} is not an actionable, verifiable outcome.")

    # R7 is intentionally NOT implemented as a structural rule (see module
    # docstring and docs/DECISIONS.md): it cannot be determined reliably from
    # structured fields without wrongly rejecting legitimate post-harvest
    # surveys.

    # R6 - the EARLIEST possible follow-up date already falls after season end.
    earliest = earliest_possible_start(
        insight.created_at,
        insight.verification.timing,
        insight.action_window_days,
    )
    if earliest is not None and earliest > SEASON_END:
        return no("window_after_season",
                  f"Earliest follow-up ({earliest.isoformat()}) is after the rabi "
                  "season ends (2027-03-31).")

    # R8 - eligible for a survey.
    return Decision(
        insight_id=iid,
        farmer_id=fid,
        survey=True,
        rule=RULE_SURVEY,
        internal_reason_code="eligible",
        schema_representable=True,
        schema_reason_code=None,
        notes=f"Actionable {res!r} outcome with verification; follow-up survey warranted.",
        warnings=warnings,
    )
