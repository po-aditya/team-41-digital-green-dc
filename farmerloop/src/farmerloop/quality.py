"""Conservative offline quality checks, NOT a semantic/agronomic safety judge.

Reports observable problems and unsupported context. A pass means only these
checks passed; relevance_score remains unknown. English/Hindi review is needed.
"""
from dataclasses import asdict, dataclass
import re

from .generate_base import SurveyValidationError, audit_survey_safety
from .models import Insight, Survey
from .validate import validate

ASSETS = {'wheat': 'गेहूँ', 'mustard': 'सरसों', 'potato': 'आलू', 'lentil': 'मसूर',
          'gram': 'चना', 'pea': 'मटर', 'maize': 'मक्का', 'onion': 'प्याज',
          'tomato': 'टमाटर', 'cabbage': 'पत्ता गोभी', 'cauliflower': 'फूलगोभी',
          'cow': 'गाय', 'buffalo': 'भैंस', 'goat': 'बकरी'}

# Input phrase -> one bounded action, not a full recommendation or new dose.
# These are development vocabulary, not learned agricultural advice.
ACTIONS = (
    (r'^(?:give (?:a light|the first) irrigation)', 'give the advised irrigation', 'सलाह के अनुसार सिंचाई की', ('irrigat', 'सिंचाई')),
    (r'^spray\b', 'apply the advised spray', 'सलाह के अनुसार छिड़काव किया', ('spray', 'छिड़काव')),
    (r'^call the nearest veterinary doctor', 'contact the veterinary doctor', 'पशु चिकित्सक से संपर्क किया', ('vet', 'पशु चिकित्सक', 'डॉक्टर')),
    (r'^top-dress urea', 'apply the advised urea', 'सलाह के अनुसार यूरिया डाला', ('urea', 'यूरिया')),
    (r'^open drains', 'open the advised drains', 'सलाह के अनुसार नालियाँ खोलीं', ('drain', 'नाल')),
    (r'^pull out wilted plants', 'remove the wilted plants', 'मुरझाए पौधे हटाए', ('wilt', 'मुरझा')),
    (r'^sow berseem or oats', 'sow the advised fodder', 'सलाह के अनुसार चारा बोया', ('fodder', 'चारा')),
    (r'^apply a sulphur fertiliser', 'apply the advised sulphur fertiliser', 'सलाह के अनुसार गंधक की खाद डाली', ('sulphur', 'गंधक')),
    (r'^apply zinc', 'apply the advised zinc', 'सलाह के अनुसार जिंक डाला', ('zinc', 'जिंक')),
    (r'^pick a variety', 'choose the advised variety', 'सलाह के अनुसार किस्म चुनी', ('variety', 'किस्म')),
    (r'^take a soil sample', 'take the soil sample', 'मिट्टी का नमूना लिया', ('soil sample', 'मिट्टी का नमूना')),
    (r'^clean the store', 'clean the store', 'भंडार की सफाई की', ('store', 'भंडार')),
    (r'^fill the gaps', 'fill the gaps in the crop', 'फसल की खाली जगहों में पौधे लगाए', ('gaps', 'खाली जगह')),
    (r'^take the animal to the next vaccination camp', 'take the animal to the vaccination camp', 'पशु को टीकाकरण शिविर ले गए', ('vaccin', 'टीकाकरण')),
)
SYMPTOMS = {
    'new drying patches': 'नए सूखते हिस्से',
    'new drooping plants': 'नए झुके हुए पौधे',
    'insects in the bins': 'भंडार में कीड़े',
    'spots on upper leaves': 'ऊपरी पत्तों पर धब्बे',
    'new yellow stripes on the upper leaves': 'ऊपरी पत्तों पर नई पीली धारियाँ',
    'new blisters on young leaves': 'नई पत्तियों पर फफोले',
    'wilting the next afternoon': 'अगली दोपहर मुरझाना',
    'more soft tubers in the heap': 'ढेर में और नरम कंद',
    'fresh damage in the whorl': 'पत्तियों के भँवर में नई क्षति',
}


AVOID = (
    ('spray', 'spraying', 'छिड़काव', ('spray', 'छिड़काव')),
    ('use the same insecticide', 'reusing the same insecticide', 'उसी कीटनाशक का दोबारा प्रयोग', ('insecticide', 'कीटनाशक')),
    ('leave undecomposed dung', 'leaving undecomposed dung in the field', 'खेत में बिना सड़ी गोबर की खाद डालना', ('dung', 'गोबर')),
    ('mix chemicals into grain', 'mixing chemicals into food grain', 'खाने के अनाज में रसायन मिलाना', ('chemicals', 'रसायन')),
    ('sell pods with holes', 'selling pods with holes', 'छेद वाली फलियाँ बेचना', ('pods', 'फलियाँ')),
    ('store wet or cut tubers', 'storing wet or cut tubers', 'गीले या कटे कंद रखना', ('tubers', 'कंद')),
)


def action_context(insight):
    text = (insight.advice_summary or '').lower().strip()
    if insight.resolution_type == 'do_not_act':
        for prefix, en, hi, markers in AVOID:
            if text.startswith('advised not to ' + prefix):
                return en, hi, markers
        return None
    text = re.sub(r'^advised to\s+', '', text)
    text = re.sub(r'^gave a plan in stages: first\s+', '', text)
    for pattern, en, hi, markers in ACTIONS:
        if re.search(pattern, text):
            return en, hi, markers
    # Official worked examples have a descriptive preamble, not practice prefixes.
    if text.startswith('these are aphids. spray '):
        return 'apply the advised spray', 'सलाह के अनुसार छिड़काव किया', ('spray', 'छिड़काव')
    if text.startswith('this needs a vet today.'):
        return 'contact the veterinary doctor', 'पशु चिकित्सक से संपर्क किया', ('vet', 'पशु चिकित्सक', 'डॉक्टर')
    if insight.resolution_type == 'plan_created' and text.startswith('plan created:') and 'buy certified seed' in text:
        return 'obtain the recommended seed', 'सुझाए गए बीज प्राप्त किए', ('seed', 'बीज')
    return None


def symptom_context(insight):
    text = (insight.advice_summary or '').lower()
    for en, hi in SYMPTOMS.items():
        if f'watch for {en}' in text:
            return en, hi
    if 'check the lower leaves' in text and 'spots spread' in text:
        return 'spots on the lower leaves', 'निचली पत्तियों पर धब्बे'
    return None


@dataclass
class QualityReport:
    checks: dict[str, bool]
    reasons: list[str]
    limitations: tuple[str, ...] = (
        'Rule-based screening, not semantic relevance or agricultural safety certification.',
        'Unsupported advice patterns require human review; Hindi needs native-speaker review.',
    )

    @property
    def passed(self):
        return not self.reasons

    def dump(self):
        return {**asdict(self), 'passed': self.passed, 'semantic_relevance_score': None}


def assess_quality(insight: Insight, survey: Survey) -> QualityReport:
    checks = {}
    checks['schema'] = not validate('survey', survey.dump())
    checks['provenance'] = survey.farmer_id == insight.farmer_id and survey.source_insight_ids == [insight.insight_id]
    lang = survey.language
    checks['language_matches_source'] = lang == insight.conversation_language and lang in ('en-IN', 'hi-IN')
    texts = [t for i in survey.items for t in [i.prompt, *[o.label for o in i.options or []]]]
    def script_ok(text):
        if lang == 'hi-IN':
            return bool(re.search('[\u0900-\u097f]', text)) and not re.search('[A-Za-z]', text)
        return bool(re.search('[A-Za-z]', text)) and not re.search('[\u0900-\u097f]', text)
    checks['language_script'] = all(script_ok(t) for t in texts)
    checks['rationale_english'] = bool(re.search('[A-Za-z]', survey.rationale)) and not re.search('[\u0900-\u097f]', survey.rationale)
    checks['unique_items_and_options'] = len({i.item_id for i in survey.items}) == len(survey.items) and all(
        len({o.value for o in i.options or []}) == len(i.options or []) and
        len({o.label.casefold() for o in i.options or []}) == len(i.options or []) for i in survey.items)
    # Existing safety audit also screens answer labels, not just prompts.
    augmented = survey.model_copy(deep=True)
    for i in augmented.items:
        i.prompt = i.prompt + ' ' + ' '.join(o.label for o in i.options or [])
    checks['safety_flags_clear'] = not audit_survey_safety(augmented).review_required
    checks['single_question'] = all(i.prompt.count('?') <= 1 and not (
        (i.type == 'survey-confirm' or {'yes', 'no'} <= {o.value for o in i.options or []}) and re.search(r'\band\b| और ', i.prompt.lower())) for i in survey.items)
    checks['answer_style'] = all(not (
        {o.value for o in i.options or []} >= {'better', 'same', 'worse'} and
        (re.match(r'^(?:for your [^,]+,\s*)?(is|are|has|have|did|does)\b', i.prompt.strip().lower()) or re.match(r'^(?:[^:]+:\s*)?क्या', i.prompt.strip()))
    ) for i in survey.items)
    prompts = ' '.join(i.prompt for i in survey.items).lower()
    asset = insight.asset.name
    expected_asset = asset if lang == 'en-IN' else ASSETS.get(asset)
    checks['asset_context'] = bool(expected_asset and expected_asset.lower() in prompts)
    action = action_context(insight)
    symptom = symptom_context(insight)
    markers = action[2] if action else symptom
    if symptom and symptom[0] == 'spots on the lower leaves':
        markers = ('spots', 'धब्ब')
    checks['abstention_polarity'] = insight.resolution_type != 'do_not_act' or bool(re.search(r'hold off|avoid|से परहेज़', prompts))
    checks['advice_context'] = bool(markers and any(marker.lower() in prompts for marker in markers))
    # Merely inserting the crop name is not a relevance proof. Require an
    # observed action/symptom marker too, and report this as lexical evidence.
    checks['no_other_asset'] = not any(
        re.search(r'\b' + re.escape(en) + r'\b', prompts) if lang == 'en-IN' else re.search(r'(?<![\w\u0900-\u097f])' + re.escape(hi) + r'(?![\w\u0900-\u097f])', prompts)
        for en, hi in ASSETS.items() if en != asset)
    return QualityReport(checks, [k for k, passed in checks.items() if not passed])


def require_quality(insight, survey):
    report = assess_quality(insight, survey)
    if not report.passed:
        raise SurveyValidationError('Survey held for review: ' + ', '.join(report.reasons))
    return report
