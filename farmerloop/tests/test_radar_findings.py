"""Verify claims, denominators and traversable evidence, not just text shape."""
from copy import deepcopy
from datetime import datetime
import json
import subprocess
import sys

import pytest

from farmerloop.radar.analyze import Thresholds, analyze
from farmerloop.radar.findings import build_findings, resolve_evidence
from farmerloop.radar.scenario import VARIANTS, build_scenario
from farmerloop.simulate import simulate


def test_two_findings_with_exact_observations():
    report = build_findings(build_scenario())
    assert len(report['findings']) == 2
    a, b = report['findings']
    assert a['kind'] == 'reported_input_access_barrier'
    assert a['rates']['reported_barrier']['numerator'] == 10
    assert a['rates']['reported_barrier']['denominator'] == 22
    assert '10 of 22' in a['observation']
    assert b['kind'] == 'feedback_evidence_gap'
    assert '5/30' in b['observation'] and '15/30' in b['observation']
    assert '0/5' in b['observation']
    assert b['evidence_assessment'] == 'limited'
    assert 'cannot establish better agricultural outcomes' in b['interpretation']
    assert a['action_status'] == b['action_status'] == 'suggested_only'
    assert len({f['finding_id'] for f in report['findings']}) == 2


@pytest.mark.parametrize('variant', VARIANTS)
def test_all_chains_resolve_and_counts_reconstruct(variant):
    scenario = build_scenario(variant=variant)
    report = build_findings(scenario)
    for finding in report['findings']:
        roles = finding['evidence_roles']
        targets = [resolve_evidence(report, ref) for ref in roles['targets']]
        assert len(targets) == finding['counts']['targets']
        def surveys(role):
            return {resolve_evidence(report, r)['survey_id'] for r in roles[role]}
        assert len(surveys('delivered')) == finding['counts']['delivered']
        assert len(surveys('barrier_answers')) == finding['counts']['barrier_answers']
        assert len(surveys('barrier_reports')) == finding['counts']['barrier_reports']
        failed = set()
        complete = set()
        attempted = set()
        for chain in finding['source_chains']:
            t, i, s, h = [resolve_evidence(report, chain[k]) for k in ('target', 'insight', 'survey', 'handoff')]
            assert t['insight_id'] == i['insight_id']
            assert t['survey_id'] == s['survey_id'] == h['survey']['survey_id']
            assert t['farmer_id'] == i['farmer_id'] == s['farmer_id']
            assert s['source_insight_ids'] == [i['insight_id']]
            for ref in chain['attempts']:
                r = resolve_evidence(report, ref)
                assert r['survey_id'] == s['survey_id']
                assert r['source_insight_ids'] == s['source_insight_ids']
                attempted.add(s['survey_id'])
                if r['status'] == 'delivery_failed': failed.add(s['survey_id'])
                if r['complete']: complete.add(s['survey_id'])
        assert len(failed - surveys('delivered')) == finding['rates']['delivery_failure']['numerator']
        assert len(attempted) == finding['rates']['delivery_failure']['denominator']
        assert len(complete & surveys('delivered')) == finding['rates']['completion_given_delivery']['numerator']
        assert finding['synthetic'] and 'SYNTHETIC' in finding['label']


def test_missing_evidence_keeps_denominator_and_explicit_gap():
    report = build_findings(build_scenario(variant='missing'))
    a = report['findings'][0]
    assert a['counts']['targets'] == 30
    assert a['counts']['barrier_reports'] == 9
    gap = a['source_chains'][0]
    assert gap['evidence_gap'] == 'no_usable_attempt_at_cutoff'
    assert gap['attempts'] == [] and gap['barrier_answer_missing']
    assert any('unknown for 1' in text for text in a['limitations'])


def test_conflicts_never_enter_evidence_archive():
    s = build_scenario()
    r = deepcopy(s.responses[0])
    r['raw_event'] = 'conflicting synthetic input'
    s.responses.append(r)
    report = build_findings(s)
    assert 'response:' + r['response_key'] not in report['records']
    assert report['findings'][0]['counts']['barrier_reports'] == 9
    assert any('diagnostics' in text for text in report['findings'][0]['limitations'])


def test_replay_does_not_change_claims_or_duplicate_chains():
    original = build_findings(build_scenario())
    replay = build_findings(build_scenario(variant='replay'))
    for a, b in zip(original['findings'], replay['findings']):
        assert a['counts'] == b['counts']
        assert a['observation'] == b['observation']
        assert a['source_chains'] == b['source_chains']


def test_no_answers_does_not_claim_zero_prevalence():
    s = build_scenario()
    s.responses = []
    report = build_findings(s)
    assert len(report['findings']) == 2
    for f in report['findings']:
        assert f['kind'] == 'feedback_evidence_gap'
        assert f['rates']['reported_barrier']['value'] is None
        assert 'proportion is undefined' in f['observation']
        assert all(c['evidence_gap'] == 'no_usable_attempt_at_cutoff' for c in f['source_chains'])


def test_small_sample_does_not_become_barrier_pattern():
    s = build_scenario()
    s.targets = s.targets[:1]
    report = build_findings(s)
    assert [f['kind'] for f in report['findings']] == ['feedback_evidence_gap']
    assert report['findings'][0]['comparison_status'] == 'insufficient_cohorts'


def test_incompatible_cohorts_do_not_get_comparative_claims():
    s = build_scenario()
    for row in s.insights[30:]: row['asset']['name'] = 'rice'
    report = build_findings(s)
    assert all(f['comparison_status'] == 'not_comparable' for f in report['findings'])
    assert all(any('No supported cross-district comparison' in x for x in f['limitations']) for f in report['findings'])


def test_no_barrier_signal_no_barrier_finding():
    s = build_scenario()
    for index in range(10):
        s.responses[index] = simulate(s.surveys[index], 'whatsapp', 'completed', sent_at=datetime(2026, 12, 25, 9))
    report = build_findings(s)
    assert [f['kind'] for f in report['findings']] == ['feedback_evidence_gap']
    assert report['findings'][0]['district'] == 'District B (synthetic)'


def test_no_forced_findings_when_thresholds_do_not_trigger():
    report = build_findings(build_scenario(), Thresholds(min_answers=1, min_barriers=100,
                                                        coverage_rate=0, delivery_failure_rate=1))
    assert report['findings'] == []
    assert report['records'] == {}


def test_expectations_and_order_do_not_drive_findings():
    s = build_scenario()
    before = s.dump()
    report = build_findings(s)
    assert s.dump() == before
    s.expected = {'invented': 999}
    for rows in (s.responses, s.targets, s.insights, s.surveys, s.handoffs): rows.reverse()
    assert build_findings(s) == report
    reference = next(iter(report['records']))
    resolve_evidence(report, reference)['changed'] = True
    assert 'changed' not in report['records'][reference]
    with pytest.raises(KeyError): resolve_evidence(report, 'response:missing')


def test_synthetic_guard():
    s = build_scenario()
    s.synthetic = False
    with pytest.raises(ValueError): build_findings(s)


def test_retry_counts_and_evidence_stay_consistent():
    s = build_scenario()
    s.responses.append(simulate(s.surveys[59], 'whatsapp', 'completed', sent_at=datetime(2026, 12, 26, 9), delivery_attempt=2))
    report = build_findings(s)
    b = report['findings'][1]
    assert '6/30' in b['observation'] and '14/30' in b['observation']
    assert len(b['source_chains'][-1]['attempts']) == 2


@pytest.mark.parametrize('language', ['hi-IN', 'en-IN'])
def test_cli_findings_json(language):
    result = subprocess.run([sys.executable, '-B', '-m', 'farmerloop.radar_demo', '--findings', '--json', '--language', language],
                            capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    assert len(report['findings']) == 2
    assert report['analysis']['cohorts'][0]['context']['language'] == language
