"""Deterministic demo analytics. Never reads Scenario.expected; no AWS calls."""
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
import json

from ..validate import validate
from .models import Scenario


@dataclass(frozen=True)
class Thresholds:
    min_answers: int = 10
    min_barriers: int = 5
    barrier_rate: float = .30
    coverage_rate: float = .50
    delivery_failure_rate: float = .30

    def __post_init__(self):
        if self.min_answers < 1 or self.min_barriers < 1:
            raise ValueError('Count thresholds must be positive')
        if any(not 0 <= x <= 1 for x in (self.barrier_rate, self.coverage_rate, self.delivery_failure_rate)):
            raise ValueError('Rate thresholds must lie in [0, 1]')


def _time(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return result


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def analyze(scenario: Scenario, thresholds: Thresholds = Thresholds()) -> dict:
    """Validate joins, retain due targets, deduplicate attempts, calculate cohorts.

    Conflicting identities are excluded in full, independent of input order.
    Conflicting accepted barrier answers suppress that survey's answer metric.
    Targets with invalid source contracts cannot be assigned a reliable cohort;
    they are reported as exclusions, never silently counted as valid targets.
    """
    cutoff = _time(scenario.observation_cutoff)
    diagnostics = []

    def note(kind, ref):
        diagnostics.append({'kind': kind, 'reference': str(ref)})

    def index(records, key, schema=None):
        groups = defaultdict(list)
        for row in records:
            if not isinstance(row, dict) or not isinstance(row.get(key), str):
                note('malformed_' + key, _canonical(row))
                continue
            groups[row[key]].append(row)
        out = {}
        for identity, rows in sorted(groups.items()):
            if len({_canonical(r) for r in rows}) != 1:
                note('conflicting_' + key, identity)
                continue
            row = rows[0]
            if schema and validate(schema, row):
                note('schema_invalid_' + key, identity)
                continue
            if len(rows) > 1:
                note('replayed_' + key, identity)
            out[identity] = row
        return out

    insights = index(scenario.insights, 'insight_id', 'insight')
    surveys = index(scenario.surveys, 'survey_id', 'survey')
    handoffs = index(scenario.handoffs, 'handoff_id', 'schedule_handoff')
    targets = index(scenario.targets, 'target_id')
    # One target per survey. Aliases cannot inflate the denominator.
    survey_targets = defaultdict(list)
    for target in targets.values():
        required = ('target_id', 'survey_id', 'insight_id', 'farmer_id', 'handoff_id', 'due_at')
        if any(not isinstance(target.get(k), str) or not target[k] for k in required):
            note('malformed_target', target['target_id'])
            continue
        survey_targets[target.get('survey_id')].append(target)
    cohorts = defaultdict(list)
    active = {}
    for sid, entries in sorted(survey_targets.items(), key=lambda x: str(x[0])):
        if len(entries) != 1:
            note('conflicting_target_survey', sid)
            continue
        t = entries[0]
        try:
            ins, survey, handoff = insights[t['insight_id']], surveys[sid], handoffs[t['handoff_id']]
            if not (ins['farmer_id'] == survey['farmer_id'] == t['farmer_id']
                    and survey['source_insight_ids'] == [ins['insight_id']]
                    and handoff['survey'] == survey
                    and t['due_at'] == survey['send_window']['not_before']):
                raise ValueError('Broken target provenance')
            if _time(t['due_at']) > cutoff:
                note('not_yet_due', t['target_id'])
                continue
            qid = scenario.context['barrier_item_id']
            question = next(i for i in survey['items'] if i['item_id'] == qid)
            if not any(o.get('follow_up') == 'could_not_get_input' for o in question.get('options', [])):
                raise ValueError('No input-access question')
            signature = {
                'crop': ins['asset']['name'], 'stage': ins['asset']['growth_stage'],
                'topic': ins['concern'], 'resolution': ins['resolution_type'],
                'season': scenario.context['season'], 'language': survey['language'],
                'preferred_channel': ins['preferred_channel'],
                'objective': scenario.context['survey_objective'],
                'window': survey['send_window'], 'question': question,
            }
            district = ins['location']['district']
            key = (district, _canonical(signature))
            cohorts[key].append(t)
            active[sid] = t
        except (KeyError, ValueError, TypeError, StopIteration):
            note('invalid_target_join', t['target_id'])

    responses = index(scenario.responses, 'response_key', 'response')
    attempts = defaultdict(list)
    for r in responses.values():
        attempts[(r['survey_id'], r['channel'], r['delivery_attempt'])].append(r)
    by_survey = defaultdict(list)
    for identity, rows in sorted(attempts.items()):
        if len(rows) != 1:
            note('conflicting_attempt', identity)
            continue
        r = rows[0]
        sid = r['survey_id']
        if sid not in active:
            note('unmatched_response', r['response_key'])
            continue
        survey = surveys[sid]
        try:
            if r['farmer_id'] != survey['farmer_id'] or r['source_insight_ids'] != survey['source_insight_ids'] or r['language'] != survey['language']:
                raise ValueError('Broken response provenance')
            if _time(r['recorded_at']) > cutoff:
                note('after_cutoff', r['response_key'])
                continue
            ts = r['timestamps']
            if ts['sent'] is None:
                raise ValueError('No evidence of attempted send')
            ordered = [_time(ts[k]) for k in ('sent', 'delivered', 'opened', 'answered') if ts[k] is not None]
            if ordered != sorted(ordered) or ordered[-1] > _time(r['recorded_at']):
                raise ValueError('Inconsistent chronology')
            if not _time(survey['send_window']['not_before']) <= ordered[0] <= _time(survey['send_window']['not_after']):
                raise ValueError('Attempt outside send window')
            if ts['delivered'] and r['failure_code'] in ('wa_undelivered', 'voice_no_answer', 'voice_busy', 'push_token_invalid', 'tg_bot_blocked'):
                raise ValueError('Contradictory delivery evidence')
            questions = {i['item_id']: i for i in survey['items']}
            if [i['item_id'] for i in r['items']] != list(questions):
                raise ValueError('Question mismatch')
            accepted = {i['item_id']: i['value'] for i in r['items'] if i['result'] == 'answered'}
            if accepted != r['answers'] or r['complete'] != (len(accepted) == len(questions)):
                raise ValueError('Inconsistent accepted answers')
            if accepted and r['answered_by'] != r['farmer_id']:
                raise ValueError('Accepted answer identity mismatch')
            if accepted and r['status'] in ('duplicate', 'stale', 'identity_mismatch'):
                raise ValueError('Discarded answers cannot be accepted')
            reasons = set()
            for q, value in accepted.items():
                item = questions[q]
                if item['type'] == 'survey-scale':
                    if not isinstance(value, int) or not item['scale_min'] <= value <= item['scale_max']:
                        raise ValueError('Invalid scale')
                    if value <= item.get('follow_up_at_or_below', -1):
                        reasons.add(item['follow_up_reason'])
                else:
                    option = next(o for o in item['options'] if o['value'] == value)
                    if option.get('follow_up'):
                        reasons.add(option['follow_up'])
            if reasons != set(r['follow_up_reasons']) or bool(reasons) != r['needs_follow_up']:
                raise ValueError('Inconsistent follow-up')
            by_survey[sid].append(r)
        except (KeyError, TypeError, ValueError, StopIteration):
            note('inconsistent_response', r['response_key'])

    output = []
    signatures = {signature for _, signature in cohorts}
    for (district, signature), members in sorted(cohorts.items()):
        counts = dict(targets=len(members), farmers=len({t['farmer_id'] for t in members}),
                      attempts=0, attempted_surveys=0, delivered=0, delivery_failures=0,
                      unknown_delivery=0, failed_attempts=0, barrier_answers=0,
                      barrier_reports=0, complete_responses=0, complete_delivered=0,
                      partial_responses=0, invalid_input_responses=0)
        evidence = {k: [] for k in ('targets', 'attempts', 'delivered', 'barrier_answers', 'barrier_reports')}
        qid = scenario.context['barrier_item_id']
        for t in sorted(members, key=lambda x: x['target_id']):
            rows = sorted(by_survey[t['survey_id']], key=lambda r: r['response_key'])
            evidence['targets'].append(t['target_id'])
            evidence['attempts'].extend(r['response_key'] for r in rows)
            counts['attempts'] += len(rows)
            counts['attempted_surveys'] += bool(rows)
            delivered = [r for r in rows if r['timestamps']['delivered']]
            failures = [r for r in rows if r['status'] == 'delivery_failed']
            counts['failed_attempts'] += len(failures)
            counts['delivered'] += bool(delivered)
            counts['delivery_failures'] += bool(failures) and not delivered
            counts['unknown_delivery'] += not delivered and not failures
            evidence['delivered'].extend(r['response_key'] for r in delivered)
            for status, key in (('partial', 'partial_responses'), ('invalid_input', 'invalid_input_responses')):
                counts[key] += sum(r['status'] == status for r in rows)
            answers = [r for r in rows if qid in r['answers']]
            counts['complete_responses'] += any(r['complete'] for r in rows)
            counts['complete_delivered'] += bool(delivered) and any(r['complete'] for r in rows)
            if len({r['answers'][qid] for r in answers}) > 1:
                note('conflicting_barrier_answers', t['survey_id'])
                continue
            counts['barrier_answers'] += bool(answers)
            evidence['barrier_answers'].extend(r['response_key'] for r in answers)
            question = next(i for i in surveys[t['survey_id']]['items'] if i['item_id'] == qid)
            barrier_values = {o['value'] for o in question['options'] if o.get('follow_up') == 'could_not_get_input'}
            barriers = [r for r in answers if r['answers'][qid] in barrier_values]
            counts['barrier_reports'] += bool(barriers)
            evidence['barrier_reports'].extend(r['response_key'] for r in barriers)
        def rate(n, d, unit):
            return dict(numerator=counts[n], denominator=counts[d], value=counts[n]/counts[d] if counts[d] else None, unit=unit)
        rates = {
            'delivery_success': rate('delivered', 'targets', 'due surveys'),
            'delivery_failure': rate('delivery_failures', 'attempted_surveys', 'attempted surveys without confirmed recovery'),
            'attempt_failure': rate('failed_attempts', 'attempts', 'distinct attempts'),
            'response_coverage': rate('barrier_answers', 'targets', 'due surveys with accepted barrier answer'),
            'completion_given_delivery': rate('complete_delivered', 'delivered', 'confirmed delivered surveys'),
            'reported_barrier': rate('barrier_reports', 'barrier_answers', 'surveys with accepted barrier answer'),
        }
        signals = []
        if counts['barrier_answers'] >= thresholds.min_answers and counts['barrier_reports'] >= thresholds.min_barriers and rates['reported_barrier']['value'] >= thresholds.barrier_rate:
            signals.append('reported_input_access_pattern')
        if rates['response_coverage']['value'] < thresholds.coverage_rate:
            signals.append('feedback_coverage_blind_spot')
        if rates['delivery_failure']['value'] is not None and rates['delivery_failure']['value'] >= thresholds.delivery_failure_rate:
            signals.append('delivery_failure_warning')
        if counts['barrier_answers'] < thresholds.min_answers:
            signals.append('insufficient_sample')
        output.append(dict(district=district, context=json.loads(signature), counts=counts,
                           rates=rates, signals=signals, evidence=evidence,
                           evidence_sufficient=('insufficient_sample' not in signals and 'feedback_coverage_blind_spot' not in signals)))
    return dict(scenario_id=scenario.scenario_id, synthetic=scenario.synthetic,
                observation_cutoff=scenario.observation_cutoff, thresholds=asdict(thresholds),
                threshold_label='Demonstration heuristics, not statistical significance',
                comparison_status=('insufficient_cohorts' if len(output) < 2 else
                                   'not_comparable' if len(signatures) > 1 else 'context_matched'),
                limitations=['Reported barriers describe respondents only; no causal or population claims.',
                             'Low or missing feedback cannot establish better agricultural outcomes.'],
                cohorts=output, diagnostics=sorted(diagnostics, key=_canonical))
