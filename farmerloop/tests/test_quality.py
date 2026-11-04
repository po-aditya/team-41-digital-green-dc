"""Boundary and adverse-case tests for offline quality screening."""
from copy import deepcopy
from datetime import datetime, timedelta, time
import json
from pathlib import Path
import pytest

from farmerloop import config
from farmerloop.generate_base import SurveyValidationError
from farmerloop.generate_contextual import ContextualSurveyGenerator
from farmerloop.generate_fake import FakeSurveyGenerator
from farmerloop.generate_bedrock import BedrockSurveyGenerator
from farmerloop.models import Insight, Survey
from farmerloop.quality import assess_quality
from farmerloop.schedule import build_handoff
from farmerloop.timing import compute_window
from farmerloop.evaluate_quality import benchmark
from tests.helpers import make_insight


def fixture(lang='en-IN'):
    ins = make_insight(conversation_language=lang,
                       advice_summary='Advised to spray a recommended insecticide as per the label.')
    w = compute_window(ins.created_at, ins.verification.timing, ins.action_window_days)
    s = ContextualSurveyGenerator().generate(ins, w)
    return ins, w, s


@pytest.mark.parametrize('lang', ['en-IN', 'hi-IN'])
def test_contextual_questions_pass_and_schedule(lang):
    ins, w, s = fixture(lang)
    report = assess_quality(ins, s)
    assert report.passed
    assert report.dump()['semantic_relevance_score'] is None
    assert 'relevance_score' not in s.self_eval.dump()
    h = build_handoff(ins, s, w, created_at=datetime.combine(w.start, time(0)))
    assert h['survey'] == s.dump()
    assert s.items[0].options[-1].value == 'no'
    assert s.items[1].options[-1].value == 'not_checked'


@pytest.mark.parametrize('problem', ['generic', 'wrong_crop', 'wrong_action', 'wrong_language',
    'rationale_hindi', 'double_question', 'double_action', 'answer_mismatch', 'duplicate_ids',
    'duplicate_values', 'unsafe_option', 'new_advice', 'personal_info', 'wrong_farmer'])
def test_unsuitable_surveys_blocked_at_handoff(problem):
    ins, w, s = fixture()
    if problem == 'generic': s = FakeSurveyGenerator().generate(ins, w)
    if problem == 'wrong_crop':
        for item in s.items: item.prompt = item.prompt.replace('wheat', 'potato')
    if problem == 'wrong_action': s.items[0].prompt = 'For your wheat, did you irrigate?'
    if problem == 'wrong_language': s.language = 'hi-IN'
    if problem == 'rationale_hindi': s.rationale = 'यह एक सर्वेक्षण है।'
    if problem == 'double_question': s.items[0].prompt += ' Did it help?'
    if problem == 'double_action':
        s.items[0].type = 'survey-confirm'
        s.items[0].options = s.items[0].options[:2]
        s.items[0].prompt = 'Did you spray and irrigate your wheat?'
    if problem == 'answer_mismatch': s.items[1].prompt = 'For your wheat, is it better?'
    if problem == 'duplicate_ids': s.items[1].item_id = s.items[0].item_id
    if problem == 'duplicate_values': s.items[0].options[1].value = s.items[0].options[0].value
    if problem == 'unsafe_option': s.items[0].options[0].label = 'Please spray more'
    if problem == 'new_advice': s.items[0].prompt += ' You should apply more next week.'
    if problem == 'personal_info': s.items[1].prompt = 'What is your phone number?'
    if problem == 'wrong_farmer': s.farmer_id = 'F-WRONG'
    # Forged approval/self-evaluation cannot bypass fresh boundary checks.
    s.self_eval = None
    assert not assess_quality(ins, s).passed
    with pytest.raises(SurveyValidationError):
        build_handoff(ins, s, w, created_at=datetime.combine(w.start, time(0)))


def test_hindi_yes_no_question_with_outcome_scale_rejected():
    ins, w, s = fixture('hi-IN')
    s.items[1].prompt = 'गेहूँ: क्या फसल बेहतर है?'
    assert 'answer_style' in assess_quality(ins, s).reasons


@pytest.mark.parametrize('resolution,advice', [
    ('plan_created', 'Gave a plan in stages: first pick a variety suited to late sowing and raise the seed rate as advised, then watch for emergence.'),
    ('wait_and_monitor', 'Advised to wait and watch for new drying patches over the next few days before acting.'),
    ('do_not_act', 'Advised not to spray when only a few insects are seen for now, because it would not help at this stage.'),
    ('escalate_to_expert', 'Advised to call the nearest veterinary doctor because fever needs a closer look.'),
])
@pytest.mark.parametrize('lang', ['en-IN', 'hi-IN'])
def test_resolution_specific_questions(resolution, advice, lang):
    ins = make_insight(resolution_type=resolution, advice_summary=advice, conversation_language=lang)
    w = compute_window(ins.created_at, ins.verification.timing, ins.action_window_days)
    s = ContextualSurveyGenerator().generate(ins, w)
    assert assess_quality(ins, s).passed
    if resolution == 'plan_created':
        assert {o.value for o in s.items[1].options} == {'yes', 'too_early', 'no', 'not_started'}
    if resolution == 'escalate_to_expert':
        assert s.items[0].options[-1].follow_up == 'could_not_reach_expert'


def test_negated_advice_not_reversed_into_positive_action():
    ins = make_insight(resolution_type='direct_action', advice_summary='Advised not to spray yet.')
    w = compute_window(ins.created_at, ins.verification.timing, ins.action_window_days)
    with pytest.raises(SurveyValidationError): ContextualSurveyGenerator().generate(ins, w)


def test_abstention_question_preserves_negative_intent():
    ins = make_insight(conversation_language='en-IN', resolution_type='do_not_act',
                       advice_summary='Advised not to spray before confirming the spots for now.')
    w = compute_window(ins.created_at, ins.verification.timing, ins.action_window_days)
    s = ContextualSurveyGenerator().generate(ins, w)
    s.items[0].prompt = 'Did you spray your wheat?'
    assert 'abstention_polarity' in assess_quality(ins, s).reasons


@pytest.mark.parametrize('over', [dict(conversation_language='ta-IN'),
    dict(advice_summary='A novel expert-defined action outside this template vocabulary.'),
    dict(asset={'name': 'unknown crop', 'category': 'crop', 'growth_stage': None})])
def test_unsupported_inputs_held_instead_of_generic_fallback(over):
    ins = make_insight(**over)
    w = compute_window(ins.created_at, ins.verification.timing, ins.action_window_days)
    with pytest.raises(SurveyValidationError): ContextualSurveyGenerator().generate(ins, w)


def test_model_output_not_silently_truncated():
    ins, w, s = fixture()
    with pytest.raises(SurveyValidationError):
        BedrockSurveyGenerator()._to_items({'items': [s.items[0].dump()]*4})


def test_mutated_survey_window_rejected():
    ins, w, s = fixture()
    s.send_window.not_before = '2026-12-01T07:00:00+05:30'
    with pytest.raises(ValueError, match='windows differ'):
        build_handoff(ins, s, w, created_at=datetime.combine(w.start, time(0)))


def test_benchmark_does_not_use_golden_answers_to_generate():
    ins, w, s = fixture()
    expected = dict(survey=True, items=[{'text': 'Completely irrelevant secret reference'}])
    run = benchmark([('test', ins.raw, expected)], ContextualSurveyGenerator(), 'en-IN')
    assert run['counts']['handoffs'] == 1
    assert run['cases'][0]['survey']['items'] == s.dump()['items']
    assert run['semantic_relevance_score'] is None
    assert run['timing']['generation_attempts'] == 1
    assert run['aws_calls'] == 0


def test_before_after_improvement_without_dropping_rejections():
    ins, w, s = fixture()
    unknown = ins.model_copy(update={'advice_summary': 'Unknown recommendation requiring review.'})
    rows = [('supported', ins.raw, None), ('unsupported', unknown.raw, None)]
    before = benchmark(rows, FakeSurveyGenerator(), 'en-IN')
    after = benchmark(rows, ContextualSurveyGenerator(), 'en-IN')
    assert before['screening_pass_rate'] == {'numerator': 0, 'denominator': 2, 'value': 0}
    assert before['counts'].get('handoffs', 0) == 0
    assert after['screening_pass_rate'] == {'numerator': 1, 'denominator': 2, 'value': .5}
    assert after['counts']['generation_rejected'] == 1
    assert len(after['cases']) == 2


@pytest.mark.parametrize('lang', ['en-IN', 'hi-IN'])
def test_official_worked_insights_supported_without_reading_reference_answers(lang):
    root = config.PARTICIPANT_PACK/'json/scenarios'
    count = 0
    for path in sorted(root.glob('*/insight.json')):
        raw = json.loads(path.read_text())
        if raw['resolution_type'] == 'generic_information': continue
        ins = Insight.model_validate({**raw, 'conversation_language': lang})
        w = compute_window(ins.created_at, ins.verification.timing, ins.action_window_days)
        survey = ContextualSurveyGenerator().generate(ins, w)
        assert assess_quality(ins, survey).passed
        count += 1
    assert count == 5


@pytest.mark.parametrize('lang', ['en-IN', 'hi-IN'])
def test_official_worked_reference_surveys_not_falsely_rejected(lang):
    for path in (config.PARTICIPANT_PACK/'json/scenarios').glob(f'*/survey.{lang}.json'):
        raw = json.loads((path.parent/'insight.json').read_text())
        ins = Insight.model_validate({**raw, 'conversation_language': lang})
        survey = Survey.model_validate(json.loads(path.read_text()))
        assert assess_quality(ins, survey).passed, (path.name, assess_quality(ins, survey).reasons)


def test_model_candidate_quality_failure_uses_screened_fallback():
    from farmerloop.demo import _generate_with_fallback
    ins, w, _ = fixture()
    class BadModel:
        name = 'mock-model'
        def generate(self, insight, window):
            return FakeSurveyGenerator().generate(insight, window)
    survey, producer = _generate_with_fallback(ins, w, BadModel())
    assert producer == 'contextual-offline-v2 (fallback)'
    assert assess_quality(ins, survey).passed
    build_handoff(ins, survey, w, created_at=datetime.combine(w.start, time(0)))


def test_failed_model_and_unsupported_fallback_cannot_schedule():
    from farmerloop.demo import _generate_with_fallback
    ins, w, _ = fixture()
    ins.advice_summary = 'Unrecognized advice requiring human review.'
    class BadModel:
        name = 'mock-model'
        def generate(self, insight, window):
            raise ValueError('mock inference failure')
    with pytest.raises(SurveyValidationError): _generate_with_fallback(ins, w, BadModel())


def test_multiple_actions_in_single_select_yes_no_question_blocked():
    ins, w, survey = fixture()
    survey.items[0].prompt = 'Did you spray and irrigate your wheat?'
    assert 'single_question' in assess_quality(ins, survey).reasons


def test_false_positive_eligibility_is_not_counted_as_golden_coverage():
    ins, _, _ = fixture()
    report = benchmark([('negative-reference', ins.raw, {'survey': False})], ContextualSurveyGenerator(), 'en-IN')
    assert report['counts']['golden_ineligible_handoffs'] == 1
    assert report['golden_eligible_coverage']['numerator'] == 0
