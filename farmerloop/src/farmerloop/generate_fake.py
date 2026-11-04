"""Deterministic template-based survey generator (no network).

Produces schema-valid two-question surveys keyed by resolution_type, in the
farmer's language (en-IN or hi-IN). The wording mirrors the golden set's
"did you act? / is it working?" pattern. This is the CI/offline default and the
reference the Bedrock generator is checked against.

Follow-up semantics are conservative: we flag follow-up ONLY on the
unambiguous bad outcome the farmer actually reports (the crop/animal is worse,
or the problem is clearly growing), using ``crop_or_animal_damaged``. The
middle "about the same" option is NOT flagged - it does not confirm the advice
failed, and over-claiming would send healthy cases to the follow-up queue.

Both generators pass their output through ``finalize_survey``, which validates
against the official schema, runs the safety audit, and attaches an honest
self_eval (no fabricated relevance score).
"""

from __future__ import annotations

from .generate_base import finalize_survey, new_survey_scaffold, resolve_language
from .models import Insight, Item, Option, Survey
from .timing import Window

# Per resolution_type: (q1_prompt, q2_prompt) for en-IN and hi-IN.
_TEMPLATES = {
    "direct_action": {
        "en-IN": ("Did you follow the advice you were given?",
                  "How is the problem now?"),
        "hi-IN": ("क्या आपने दी गई सलाह पर अमल किया?",
                  "अब समस्या कैसी है?"),
    },
    "wait_and_monitor": {
        "en-IN": ("Did you watch the crop as advised?",
                  "Is the problem growing?"),
        "hi-IN": ("क्या आपने सलाह अनुसार निगरानी की?",
                  "क्या समस्या बढ़ रही है?"),
    },
    "do_not_act": {
        "en-IN": ("Did you hold off as advised?",
                  "How is it now?"),
        "hi-IN": ("क्या आपने सलाह अनुसार इंतज़ार किया?",
                  "अब स्थिति कैसी है?"),
    },
    "plan_created": {
        "en-IN": ("Did you start the plan's first step?",
                  "Is the plan working so far?"),
        "hi-IN": ("क्या आपने योजना का पहला कदम शुरू किया?",
                  "क्या योजना अब तक काम कर रही है?"),
    },
    "escalate_to_expert": {
        "en-IN": ("Did you reach the expert?",
                  "Is the crop or animal better?"),
        "hi-IN": ("क्या आप विशेषज्ञ तक पहुँच पाए?",
                  "क्या फसल या पशु बेहतर है?"),
    },
}

# q2 "how is it now" outcome options. Only the clearly-bad outcome ("worse")
# carries a follow-up reason; "same" is intentionally unflagged.
# (value, en label, hi label, follow_up or None)   labels <= 20 chars.
_OUTCOME_OPTIONS = [
    ("better", "Better", "बेहतर", None),
    ("same", "Same as before", "पहले जैसा", None),
    ("worse", "Worse", "पहले से खराब", "crop_or_animal_damaged"),
]
# "is the problem growing?" - only "yes, growing" is the clearly-bad outcome.
_GROWING_OPTIONS = [
    ("no", "No", "नहीं", None),
    ("same", "About the same", "लगभग वैसा ही", None),
    ("yes", "Yes, growing", "हाँ, बढ़ रही", "crop_or_animal_damaged"),
]
_YESNO = {
    "en-IN": [("yes", "Yes"), ("no", "No")],
    "hi-IN": [("yes", "हाँ"), ("no", "नहीं")],
}


class FakeSurveyGenerator:
    """Deterministic, offline survey generator."""

    name = "fake"

    def generate(self, insight: Insight, window: Window) -> Survey:
        # One resolved language, used for BOTH the questions and the declared
        # survey language - they can never disagree.
        lang = resolve_language(insight)
        res = insight.resolution_type or "direct_action"
        tmpl = _TEMPLATES.get(res, _TEMPLATES["direct_action"])
        q1_text, q2_text = tmpl[lang]

        q1 = Item(
            item_id="q1",
            type="survey-confirm",
            prompt=q1_text,
            options=[Option(value=v, label=l) for v, l in _YESNO[lang]],
        )

        opt_src = _GROWING_OPTIONS if res == "wait_and_monitor" else _OUTCOME_OPTIONS
        q2_opts = [
            Option(value=value, label=(hi if lang == "hi-IN" else en), follow_up=fu)
            for value, en, hi, fu in opt_src
        ]
        q2 = Item(
            item_id="q2",
            type="survey-single-select",
            prompt=q2_text,
            options=q2_opts,
        )

        scaffold = new_survey_scaffold(insight, window, lang)
        survey = Survey(
            **scaffold,
            items=[q1, q2],
            rationale=(
                f"Template follow-up for {res} advice: confirm the farmer acted, "
                "then check the outcome; only a clearly worse outcome flags follow-up."
            ),
            self_eval=None,  # set honestly by finalize_survey.
        )
        # Same validation + safety gate as the Bedrock generator.
        return finalize_survey(survey)
