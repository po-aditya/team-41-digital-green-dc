from copy import deepcopy
from datetime import datetime
import pytest
from farmerloop.radar.analyze import analyze, Thresholds
from farmerloop.radar.scenario import build_scenario, VARIANTS
from farmerloop.simulate import simulate


def district(result, letter):
    return next(c for c in result['cohorts'] if c['district'] == f'District {letter} (synthetic)')


@pytest.mark.parametrize('variant', VARIANTS)
def test_fixture_metrics(variant):
    s = build_scenario(variant=variant)
    result = analyze(s)
    for letter in ('A', 'B'):
        counts = district(result, letter)['counts']
        for key in ('targets', 'attempts', 'delivered', 'barrier_answers', 'barrier_reports',
                    'complete_responses', 'delivery_failures', 'partial_responses', 'invalid_input_responses'):
            assert counts[key] == s.expected[letter][key], (variant, key)
    assert district(result, 'A')['counts']['unknown_delivery'] == (variant in ('missing', 'malformed'))


def test_base_signals_and_denominators():
    result = analyze(build_scenario())
    a, b = district(result, 'A'), district(result, 'B')
    assert a['rates']['reported_barrier']['value'] == 10/22
    assert b['rates']['reported_barrier']['value'] == 0
    assert a['rates']['completion_given_delivery']['value'] == 22/27
    assert b['rates']['response_coverage']['value'] == 5/30
    assert a['signals'] == ['reported_input_access_pattern']
    assert set(b['signals']) == {'feedback_coverage_blind_spot', 'delivery_failure_warning', 'insufficient_sample'}
    assert not b['evidence_sufficient']
    assert result['comparison_status'] == 'context_matched'


def test_expectations_are_never_used_and_order_is_irrelevant():
    s = build_scenario()
    expected = analyze(s)
    s.expected = {'fake': {'targets': 99999}}
    for rows in (s.insights, s.targets, s.surveys, s.handoffs, s.responses):
        rows.reverse()
    assert analyze(s) == expected


def test_conflicting_response_identity_excluded_entirely():
    s = build_scenario()
    other = deepcopy(s.responses[0])
    other['raw_event'] = 'conflicting observation'
    s.responses.append(other)
    result = analyze(s)
    assert district(result, 'A')['counts']['barrier_reports'] == 9
    assert district(result, 'A')['counts']['targets'] == 30
    assert any(d['kind'] == 'conflicting_response_key' for d in result['diagnostics'])
    s.responses.reverse()
    assert analyze(s) == result


def test_attempt_alias_cannot_inflate_counts():
    s = build_scenario()
    r = deepcopy(s.responses[0])
    r['response_key'] = 'sim-alias'
    s.responses.append(r)
    result = analyze(s)
    assert district(result, 'A')['counts']['attempts'] == 29
    assert any(d['kind'] == 'conflicting_attempt' for d in result['diagnostics'])


def test_retry_recovery_separates_attempts_from_reach():
    s = build_scenario()
    r = simulate(s.surveys[29], 'whatsapp', 'completed',
                 sent_at=datetime(2026, 12, 26, 9), delivery_attempt=2)
    s.responses.append(r)
    a = district(analyze(s), 'A')
    assert a['counts']['attempts'] == 31
    assert a['counts']['attempted_surveys'] == 30
    assert a['counts']['delivered'] == 28
    assert a['counts']['delivery_failures'] == 2
    assert a['counts']['failed_attempts'] == 3
    assert a['rates']['attempt_failure']['value'] == 3/31


def test_unknown_delivery_is_not_failure():
    s = build_scenario()
    s.responses[22]['timestamps']['delivered'] = None  # Expired without answer.
    a = district(analyze(s), 'A')
    assert a['counts']['unknown_delivery'] == 1
    assert a['counts']['delivery_failures'] == 3
    assert a['counts']['delivered'] == 26


@pytest.mark.parametrize('mutation', ['farmer', 'answer', 'chronology', 'followup'])
def test_inconsistent_records_do_not_remove_targets(mutation):
    s = build_scenario()
    r = s.responses[0]
    if mutation == 'farmer': r['farmer_id'] = 'SIM-F-WRONG'
    if mutation == 'answer': r['answers']['q2'] = 'invented'
    if mutation == 'chronology': r['timestamps']['answered'] = '2026-12-01T09:00:00+05:30'
    if mutation == 'followup': r['follow_up_reasons'] = []
    a = district(analyze(s), 'A')
    assert a['counts']['targets'] == 30
    assert a['counts']['barrier_reports'] == 9
    assert a['counts']['unknown_delivery'] == 1


def test_incompatible_contexts_are_split():
    s = build_scenario()
    s.insights[30]['asset']['name'] = 'rice'
    result = analyze(s)
    assert result['comparison_status'] == 'not_comparable'
    assert len(result['cohorts']) == 3
    assert sum(c['counts']['targets'] for c in result['cohorts']) == 60


def test_not_due_and_after_cutoff_exclusions():
    s = build_scenario()
    s.observation_cutoff = '2026-12-24T20:00:00+05:30'
    assert analyze(s)['cohorts'] == []
    s.observation_cutoff = '2026-12-25T08:00:00+05:30'
    result = analyze(s)
    assert district(result, 'A')['counts']['targets'] == 30
    assert district(result, 'A')['counts']['attempts'] == 0
    assert district(result, 'A')['rates']['reported_barrier']['value'] is None


def test_small_sample_and_zero_denominators():
    s = build_scenario()
    s.targets = s.targets[:1]
    a = district(analyze(s), 'A')
    assert a['rates']['reported_barrier']['value'] == 1
    assert 'reported_input_access_pattern' not in a['signals']
    assert 'insufficient_sample' in a['signals']
    s.responses = []
    a = district(analyze(s), 'A')
    assert a['rates']['completion_given_delivery']['value'] is None
    assert a['rates']['delivery_failure']['value'] is None


def test_conflicting_answers_not_resolved_by_latest_wins():
    s = build_scenario()
    s.responses.append(simulate(s.surveys[0], 'whatsapp', 'completed',
                                sent_at=datetime(2026, 12, 26, 9), delivery_attempt=2))
    result = analyze(s)
    a = district(result, 'A')
    assert a['counts']['delivered'] == 27
    assert a['counts']['barrier_answers'] == 21
    assert any(d['kind'] == 'conflicting_barrier_answers' for d in result['diagnostics'])


def test_thresholds_configurable_and_no_forced_positive():
    result = analyze(build_scenario(), Thresholds(min_barriers=11))
    assert 'reported_input_access_pattern' not in district(result, 'A')['signals']
    for kwargs in ({'min_answers': 0}, {'coverage_rate': 2}):
        with pytest.raises(ValueError): Thresholds(**kwargs)


def test_evidence_references_resolve_and_inputs_unchanged():
    s = build_scenario()
    original = s.dump()
    result = analyze(s)
    assert s.dump() == original
    response_ids = {r['response_key'] for r in s.responses}
    target_ids = {t['target_id'] for t in s.targets}
    for c in result['cohorts']:
        for kind, refs in c['evidence'].items():
            assert set(refs) <= (target_ids if kind == 'targets' else response_ids)


def test_no_barriers_does_not_create_a_pattern():
    s = build_scenario()
    for i in range(10):
        s.responses[i] = simulate(s.surveys[i], 'whatsapp', 'completed', sent_at=datetime(2026, 12, 25, 9))
    a = district(analyze(s), 'A')
    assert a['counts']['barrier_reports'] == 0
    assert a['signals'] == []


def test_missing_source_is_explicitly_excluded():
    s = build_scenario()
    s.insights.pop(0)
    result = analyze(s)
    assert district(result, 'A')['counts']['targets'] == 29
    assert any(d['kind'] == 'invalid_target_join' for d in result['diagnostics'])


def test_duplicate_target_not_counted_twice():
    s = build_scenario()
    s.targets.append(deepcopy(s.targets[0]))
    assert district(analyze(s), 'A')['counts']['targets'] == 30


def test_malformed_target_and_wrong_answer_identity_are_diagnosed():
    s = build_scenario()
    s.targets[0]['survey_id'] = []
    s.responses[1]['answered_by'] = 'SIM-F-WRONG'
    result = analyze(s)
    kinds = {d['kind'] for d in result['diagnostics']}
    assert {'malformed_target', 'inconsistent_response'} <= kinds
    assert district(result, 'A')['counts']['barrier_reports'] == 8
