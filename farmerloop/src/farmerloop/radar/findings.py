"""Evidence-backed, deterministic demo findings; no generated or causal claims."""
from copy import deepcopy
from hashlib import sha256
import json

from .analyze import Thresholds, analyze
from .models import Scenario


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def resolve_evidence(report: dict, reference: str) -> dict:
    """Resolve a local record reference, returning an independent snapshot.

    These are internal references, not web URLs. Missing references raise rather
    than returning invented evidence. The UI can render this same lookup later.
    """
    return deepcopy(report['records'][reference])


def build_findings(scenario: Scenario, thresholds: Thresholds = Thresholds()) -> dict:
    """Recompute analysis from inputs, then attach only its contributing records.

    No externally supplied analysis or fixture expectations are trusted. Entire
    source chains support denominators as well as positive observations.
    """
    if scenario.synthetic is not True:
        raise ValueError('This finding workflow is restricted to explicitly synthetic demos')
    analysis = analyze(scenario, thresholds)
    report = dict(scenario_id=scenario.scenario_id, synthetic=True,
                  label='SYNTHETIC DEMONSTRATION — not real regional evidence',
                  observation_cutoff=scenario.observation_cutoff,
                  analysis=analysis, findings=[], records={})
    indexes = {}
    for kind, records, field in (
        ('target', scenario.targets, 'target_id'),
        ('insight', scenario.insights, 'insight_id'),
        ('survey', scenario.surveys, 'survey_id'),
        ('handoff', scenario.handoffs, 'handoff_id'),
        ('response', scenario.responses, 'response_key'),
    ):
        index = {}
        for r in records:
            if isinstance(r, dict) and isinstance(r.get(field), str):
                index.setdefault(r[field], []).append(r)
        indexes[kind] = index

    def reference(kind, identity):
        candidates = indexes[kind].get(identity, [])
        if not candidates or len({_canonical(r) for r in candidates}) != 1:
            raise ValueError(f'Unresolvable or conflicting evidence: {kind}:{identity}')
        ref = f'{kind}:{identity}'
        report['records'][ref] = deepcopy(candidates[0])
        return ref

    for cohort in analysis['cohorts']:
        signals = set(cohort['signals'])
        kinds = []
        if 'reported_input_access_pattern' in signals:
            kinds.append('reported_input_access_barrier')
        if signals & {'feedback_coverage_blind_spot', 'delivery_failure_warning', 'insufficient_sample'}:
            kinds.append('feedback_evidence_gap')
        if not kinds:
            continue
        evidence = cohort['evidence']
        roles = {key: [reference('target' if key == 'targets' else 'response', ident)
                       for ident in sorted(set(identities))]
                 for key, identities in evidence.items()}
        chains = []
        for target_ref in roles['targets']:
            target = report['records'][target_ref]
            attempts = [ref for ref in roles['attempts']
                        if report['records'][ref]['survey_id'] == target['survey_id']]
            chains.append(dict(
                target=target_ref,
                insight=reference('insight', target['insight_id']),
                survey=reference('survey', target['survey_id']),
                handoff=reference('handoff', target['handoff_id']),
                attempts=attempts,
                evidence_gap=('no_usable_attempt_at_cutoff' if not attempts else
                              'delivery_unconfirmed' if not any(
                                  report['records'][r]['timestamps']['delivered'] or
                                  report['records'][r]['status'] == 'delivery_failed' for r in attempts)
                              else None),
                barrier_answer_missing=not any(
                    r in roles['barrier_answers'] for r in attempts),
            ))
        counts, rates = cohort['counts'], cohort['rates']
        limitations = list(analysis['limitations']) + [
            'All farmers, interactions and district patterns are synthetic.',
            'Detection thresholds are configurable demonstration heuristics, not statistical significance.',
            'Seed access answers do not establish crop outcomes or explain why inputs were unavailable.',
        ]
        if not cohort['evidence_sufficient']:
            limitations.append('Feedback coverage or sample size is insufficient under the demo heuristics.')
        if analysis['comparison_status'] != 'context_matched':
            limitations.append('No supported cross-district comparison: ' + analysis['comparison_status'] + '.')
        if analysis['diagnostics']:
            limitations.append('The analysis has input diagnostics; consult analysis.diagnostics for rejected, conflicting or excluded evidence. Diagnostics apply to the whole scenario.')
        if counts['unknown_delivery']:
            limitations.append(f"Delivery outcome is unknown for {counts['unknown_delivery']} due surveys; absence of evidence is not a confirmed delivery failure.")
        for kind in kinds:
            if kind == 'reported_input_access_barrier':
                title = 'Reported difficulty obtaining recommended inputs'
                observation = (f"{counts['barrier_reports']} of {counts['barrier_answers']} surveys with an accepted "
                               f"barrier-question answer in {cohort['district']} report inability to obtain the recommended seed. "
                               f"Barrier-answer coverage is {counts['barrier_answers']}/{counts['targets']} due surveys.")
                interpretation = 'This is a pattern among respondents that merits investigation. It does not establish regional prevalence or an effect caused by FarmerChat.'
                action = 'Ask a human reviewer to examine the linked reports and investigate input availability and affordability as possible explanations, not established causes.'
            else:
                title = 'Regional feedback evidence gap'
                failure = rates['delivery_failure']
                observation = (f"{counts['barrier_answers']}/{counts['targets']} due surveys have an accepted barrier answer "
                               f"in {cohort['district']}; {counts['delivered']}/{counts['targets']} have confirmed delivery. "
                               f"{failure['numerator']}/{failure['denominator']} attempted surveys have explicit delivery failures "
                               f"without confirmed recovery. There are {counts['barrier_reports']}/{counts['barrier_answers']} "
                               "reported barriers among barrier-question respondents.")
                if not counts['barrier_answers']:
                    observation += ' The barrier proportion is undefined because there are no valid barrier answers.'
                interpretation = 'Feedback is limited or delivery is problematic under the demo heuristics. Few or zero reports cannot establish better agricultural outcomes, farmer trust, or the cause of nonresponse.'
                action = 'Ask a human reviewer to inspect delivery records and feedback gaps before comparing agricultural outcomes; assess outreach reliability and whether more evidence is needed.'
            identity = _canonical([scenario.scenario_id, cohort['district'], cohort['context'], kind])
            finding = dict(
                finding_id='sim-finding-' + sha256(identity.encode()).hexdigest()[:16],
                kind=kind, synthetic=True, label=report['label'], title=title,
                district=cohort['district'], context=deepcopy(cohort['context']),
                observation_cutoff=scenario.observation_cutoff,
                observation=observation, interpretation=interpretation,
                human_review_action=action, action_status='suggested_only',
                counts=deepcopy(counts), rates=deepcopy(rates),
                triggering_signals=sorted(signals & ({'reported_input_access_pattern'} if kind == 'reported_input_access_barrier'
                    else {'feedback_coverage_blind_spot', 'delivery_failure_warning', 'insufficient_sample'})),
                evidence_assessment='limited' if not cohort['evidence_sufficient'] else 'descriptive_only',
                comparison_status=analysis['comparison_status'],
                limitations=list(limitations), evidence_roles=deepcopy(roles), source_chains=deepcopy(chains),
            )
            report['findings'].append(finding)
    return report
