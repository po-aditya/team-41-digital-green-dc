"""Bounded bilingual offline templates. Unsupported context is held for review.

Reads insight fields only, never golden answers. FakeSurveyGenerator is retained
as the v1 baseline. This is not a general translation or semantic model.
"""
from .generate_base import SurveyValidationError, finalize_survey, new_survey_scaffold
from .models import Item, Option, Survey
from .quality import ASSETS, action_context, symptom_context, require_quality


class ContextualSurveyGenerator:
    name = 'contextual-offline-v2'

    def generate(self, insight, window):
        lang = insight.conversation_language
        if lang not in ('en-IN', 'hi-IN') or insight.asset.name not in ASSETS:
            raise SurveyValidationError('Unsupported language or asset; human review required')
        hi = lang == 'hi-IN'
        asset = ASSETS[insight.asset.name] if hi else insight.asset.name
        action, symptom = action_context(insight), symptom_context(insight)
        res = insight.resolution_type
        if res == 'wait_and_monitor' and symptom:
            context = symptom[1] if hi else symptom[0]
            q1 = f'{asset}: क्या आपने {context} की जाँच की?' if hi else f'For your {asset}, did you check for {context}?'
        elif res == 'do_not_act' and action:
            q1 = f'{asset}: क्या आपने {action[1]} से परहेज़ किया?' if hi else f'For your {asset}, did you hold off on {action[0]} as advised?'
        elif res in ('direct_action', 'plan_created', 'escalate_to_expert') and action:
            q1 = f'{asset}: क्या आपने {action[1]}?' if hi else f'For your {asset}, did you {action[0]}?'
        else:
            raise SurveyValidationError('No supported offline template for this advice; human review required')
        def option(value, en, hindi, reason=None):
            return Option(value=value, label=hindi if hi else en, follow_up=reason)
        q1opts = [option('yes', 'Yes', 'हाँ'), option('not_yet', 'Not yet', 'अभी नहीं'),
                  option('no', 'No', 'नहीं')]
        if res == 'escalate_to_expert':
            q1opts[-1] = option('could_not_reach', 'Could not reach', 'संपर्क नहीं हो पाया', 'could_not_reach_expert')
        items = [Item(item_id='q1', type='survey-single-select', prompt=q1, options=q1opts)]
        if res == 'plan_created':
            q2 = f'{asset}: क्या योजना अब तक काम कर रही है?' if hi else f'For your {asset}, is the plan working so far?'
            opts = [option('yes', 'Yes', 'हाँ'), option('too_early', 'Too early to say', 'अभी कहना कठिन'),
                    option('no', 'No', 'नहीं', 'advice_did_not_work'), option('not_started', 'Not started', 'शुरू नहीं किया')]
        elif res == 'escalate_to_expert':
            q2 = f'{asset}: क्या विशेषज्ञ की सलाह से मदद मिली?' if hi else f'For your {asset}, did the expert advice help?'
            opts = [option('yes', 'Yes', 'हाँ'), option('no', 'No', 'नहीं', 'advice_did_not_work'),
                    option('not_met', 'Not met yet', 'अभी नहीं मिले')]
        else:
            q2 = f'अब {asset} की स्थिति कैसी है?' if hi else f'How is your {asset} now?'
            opts = [option('better', 'Better', 'बेहतर'), option('same', 'Same as before', 'पहले जैसा'),
                    option('worse', 'Worse', 'पहले से खराब', 'crop_or_animal_damaged'),
                    option('not_checked', 'Not checked', 'जाँच नहीं की')]
        items.append(Item(item_id='q2', type='survey-single-select', prompt=q2, options=opts))
        survey = finalize_survey(Survey(**new_survey_scaffold(insight, window, lang), items=items,
            rationale='Follow up on one identified action or observation, then ask about the reported outcome. Timing follows the insight action window and supplied timing rules.'))
        require_quality(insight, survey)
        return survey
