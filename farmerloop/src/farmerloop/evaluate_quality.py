"""Offline before/after screening benchmark; not an LLM or human quality grade.

Golden references are shown beside candidates for review, never fed into either
writer. This dataset informed template development; results are not held-out
accuracy. Unsupported cases remain in coverage denominators.
"""
import argparse
from collections import Counter
from datetime import datetime, time, timedelta
import json
from time import perf_counter

from . import config
from .dataio import load_golden
from .decide import decide
from .generate_fake import FakeSurveyGenerator
from .generate_contextual import ContextualSurveyGenerator
from .models import Insight, Survey
from .quality import assess_quality
from .schedule import build_handoff
from .timing import compute_window
from .validate import validate


def benchmark(cases, generator, language, include_cases=True):
    """cases=(id, raw insight, reference or None); fixed timing for reproducibility."""
    started = perf_counter()
    counts = Counter(input_rows=len(cases))
    failures = Counter()
    rows, elapsed = [], []
    for identity, raw, expected in cases:
        row = dict(case_id=identity, reference=expected)
        try:
            if validate('insight', raw):
                raise ValueError('Input schema invalid')
            ins = Insight.model_validate({**raw, 'conversation_language': language})
        except (ValueError, TypeError):
            counts['invalid_inputs'] += 1
            rows.append({**row, 'status': 'invalid_input'})
            continue
        decision = decide(ins)
        if expected is not None:
            counts['golden_decisions_correct'] += decision.survey == expected['survey']
            counts['golden_expected_eligible'] += bool(expected['survey'])
        if not decision.survey:
            counts['ineligible'] += 1
            rows.append({**row, 'status': 'ineligible', 'reason': decision.internal_reason_code})
            continue
        counts['eligible'] += 1
        window = compute_window(ins.created_at, ins.verification.timing, ins.action_window_days)
        if window is None:
            counts['unschedulable'] += 1
            rows.append({**row, 'status': 'unschedulable'})
            continue
        t0 = perf_counter()
        try:
            survey = generator.generate(ins, window)
            elapsed.append(perf_counter()-t0)
            counts['generated'] += 1
            report = assess_quality(ins, survey)
            row.update(survey=survey.dump(), screening=report.dump())
            if report.passed:
                counts['screen_passed'] += 1
            else:
                failures.update(report.reasons)
            # Call the real boundary even when checks fail, to verify rejection.
            created = datetime.combine(window.start-timedelta(days=1), time(19))
            try:
                build_handoff(ins, survey, window, created_at=created)
                counts['handoffs'] += 1
                if expected is not None:
                    counts['golden_eligible_handoffs' if expected['survey'] else 'golden_ineligible_handoffs'] += 1
                if not report.passed:
                    raise RuntimeError('Quality gate bypass detected')
                row['status'] = 'handoff_ready'
            except ValueError as exc:
                counts['held_for_review'] += 1
                row.update(status='held_for_review', reason=str(exc))
        except ValueError as exc:
            if len(elapsed) < counts['eligible']-counts['unschedulable']:
                elapsed.append(perf_counter()-t0)
            counts['generation_rejected'] += 1
            failures[str(exc)] += 1
            row.update(status='generation_rejected', reason=str(exc))
        if expected is not None and expected.get('survey') and 'survey' in row:
            reference_window = expected.get('send_window', {})
            if reference_window:
                actual = row['survey']['send_window']
                match = (actual['not_before'], actual['not_after']) == (reference_window.get('start'), reference_window.get('end'))
                counts['window_compared'] += 1
                counts['window_exact_matches'] += match
                row['golden_window_exact_match'] = match
            # Golden items may have show_if, absent from official survey schema.
            row['reference_review_required'] = True
        rows.append(row)
    total = perf_counter()-started
    eligible = counts['eligible']
    result = dict(generator=generator.name, language=language, counts=dict(counts),
                  screening_pass_rate=dict(numerator=counts['screen_passed'], denominator=eligible,
                                           value=counts['screen_passed']/eligible if eligible else None),
                  failures=dict(failures),
                  timing=dict(batch_wall_seconds=total, generation_attempts=len(elapsed),
                              generation_seconds_total=sum(elapsed),
                              mean_generation_attempt_seconds=sum(elapsed)/len(elapsed) if elapsed else None),
                  aws_calls=0, model_tokens=0, inference_cost_usd=0,
                  golden_eligible_coverage=dict(numerator=counts['golden_eligible_handoffs'],
                      denominator=counts['golden_expected_eligible'],
                      value=counts['golden_eligible_handoffs']/counts['golden_expected_eligible'] if counts['golden_expected_eligible'] else None),
                  semantic_relevance_score=None)
    if include_cases:
        result['cases'] = rows
    return result


def evaluate(*, practice=False):
    loaded = load_golden()
    cases = [(c.golden_id, c.raw_insight, c.expected) for c in loaded.cases]
    report = dict(label='Offline development-set screening, not semantic relevance accuracy',
                  limitations=[
                      'Rules and templates were developed using this pack; no held-out generalization claim.',
                      'Script checks do not establish fluent Hindi or English; human review required.',
                      'Lexical action/crop checks cannot prove entailment, absence of new advice, or agricultural safety.',
                      'Golden conditional show_if items cannot be copied into the official survey schema.',
                      'Timing follows rules.json (07:00); golden windows often start at 09:00.',
                      'Offline latency/cost is not Bedrock latency/cost. Zero inference cost excludes compute.',
                  ], golden_rows=loaded.total, golden_load_failures=len(loaded.errors), runs=[])
    if loaded.errors:
        raise ValueError('Golden load failures must be resolved before publishing this benchmark')
    for language in ('en-IN', 'hi-IN'):
        for generator in (FakeSurveyGenerator(), ContextualSurveyGenerator()):
            report['runs'].append(benchmark(cases, generator, language))
    worked = []
    for path in sorted((config.PARTICIPANT_PACK/'json/scenarios').glob('*/insight.json')):
        raw = json.loads(path.read_text())
        # Worked examples use the full official schema; preserve them for review.
        worked.append((path.parent.name, raw, None))
    report['worked_examples'] = []
    for language in ('en-IN', 'hi-IN'):
        run = benchmark(worked, ContextualSurveyGenerator(), language)
        for row in run['cases']:
            path = config.PARTICIPANT_PACK/'json/scenarios'/row['case_id']/f'survey.{language}.json'
            if path.exists():
                reference = json.loads(path.read_text())
                row['official_reference'] = reference
                raw = next(raw for name, raw, _ in worked if name == row['case_id'])
                ins = Insight.model_validate({**raw, 'conversation_language': language})
                row['reference_screening'] = assess_quality(ins, Survey.model_validate(reference)).dump()
        report['worked_examples'].append(run)
    if practice:
        raw_rows = [(str(n), json.loads(line), None) for n, line in enumerate(
            config.INSIGHTS_JSONL.read_text().splitlines(), 1) if line.strip()]
        report['practice'] = benchmark(raw_rows, ContextualSurveyGenerator(), 'en-IN', include_cases=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--practice', action='store_true', help='also process every practice row offline')
    args = parser.parse_args()
    report = evaluate(practice=args.practice)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report['label'])
        for run in report['runs']:
            print(run['generator'], run['language'], json.dumps(run['counts']),
                  'mean generation seconds:', run['timing']['mean_generation_attempt_seconds'])
        if args.practice:
            print('Practice:', json.dumps(report['practice'], indent=2))
        print('Semantic relevance remains unscored. Use --json for candidate/reference review pairs.')


if __name__ == '__main__':
    main()
