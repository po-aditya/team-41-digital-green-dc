"""Narrow offline template for the synthetic wheat-seed access scenario.

This does not replace the general FakeSurveyGenerator or add farming advice.
Only an explicit inability to obtain seed flags could_not_get_input.
"""

from ..generate_base import finalize_survey, new_survey_scaffold
from ..models import Insight, Item, Option, Survey
from ..timing import Window


def input_access_survey(insight: Insight, window: Window) -> Survey:
    if (insight.asset.name != "wheat" or insight.concern != "variety_selection"
            or insight.resolution_type != "plan_created"):
        raise ValueError("Input-access demo requires the wheat variety-plan context")
    lang = insight.conversation_language
    if lang not in ("hi-IN", "en-IN"):
        raise ValueError("Input-access demo supports hi-IN and en-IN only")
    hindi = lang == "hi-IN"
    survey = Survey(
        **new_survey_scaffold(insight, window, lang),
        items=[
            Item(item_id="q1", type="survey-confirm",
                 prompt=("क्या आपने सुझाए गए गेहूँ के बीज लेने की कोशिश की?" if hindi
                         else "Did you try to obtain the recommended wheat seed?"),
                 options=[Option(value="yes", label="हाँ" if hindi else "Yes"),
                          Option(value="no", label="नहीं" if hindi else "No")]),
            Item(item_id="q2", type="survey-single-select",
                 prompt=("सुझाए गए गेहूँ के बीज लेने की कोशिश का क्या नतीजा रहा?" if hindi
                         else "What happened when you tried to obtain the recommended wheat seed?"),
                 options=[
                     Option(value="obtained", label="बीज मिल गए" if hindi else "Obtained seed"),
                     Option(value="could_not_obtain", label="बीज नहीं मिल पाए" if hindi else "Could not obtain",
                            follow_up="could_not_get_input"),
                     Option(value="not_tried", label="कोशिश नहीं की" if hindi else "Did not try"),
                 ]),
        ],
        rationale="Synthetic wheat-plan follow-up: distinguish reported seed-access difficulty from not trying. No cause or crop outcome is inferred.",
    )
    return finalize_survey(survey)
