# Survey quality checkpoint — offline screening and evaluation

The user approved improving FarmerLoop's questions, comparing them with Digital
Green examples, and preventing unsuitable surveys from being scheduled. This
checkpoint changes FarmerLoop only. No live inference, teammate edits, new
packages, commits or publishing were authorized or performed.

## What changed

- `quality.py`: schema, provenance, English/Hindi script, English rationale,
  duplicate item/option, existing safety flags (including option labels),
  compound-question, answer-style, crop/action context, conflicting crop and
  negative-intent checks. It returns named checks and reasons, not a fabricated
  semantic relevance score.
- `generate_contextual.py`: bilingual v2 templates selected from the insight's
  advice, asset and resolution. Questions name the crop/animal and one identified
  action or symptom. Plan questions offer yes/too early/no/not started; expert
  questions distinguish not-yet from could-not-reach. Unknown patterns are held
  for review instead of silently receiving generic questions.
- `schedule.build_handoff`: fresh quality checks at the scheduling boundary,
  including direct callers, and agreement between survey and supplied window.
  A schema-valid or model-self-approved survey can still be rejected.
- `demo` and `feedback_demo`: use v2 by default. The live-demo path screens a model
  candidate before accepting it and uses the same screened offline fallback.
  If both are unsuitable, generation stops; it does not schedule generic output.
- `generate_bedrock`: more explicit prompt instructions about context, single
  actions, answer styles and English rationale. Oversized item lists are rejected
  instead of silently truncated. Changes are tested with mocks, not live AWS.
- `evaluate_quality.py`: repeatable v1/v2 comparison against all 150 golden rows
  and the six worked scenarios, plus optional full practice run. JSON includes
  source-reference questions beside generated surveys for human review.

The existing `FakeSurveyGenerator` is deliberately unchanged as the v1 baseline.
Its old generic output now fails the new scheduling gate. Callers needing a
handoff should use `ContextualSurveyGenerator` or a screened model candidate.
Existing scheduling tests retain their assertions but use meaningful advice
instead of the old placeholder `advice_summary="a"`, and use v2 generation.

## What the checks prove—and do not prove

A pass establishes only the documented deterministic checks. A lexical crop and
advice match is not proof of semantic relevance, fluent Hindi, correct agronomy,
absence of all harmful instructions, or coverage of all aspects of advice.
The safety check is still heuristic. Human/MEL review and later authorized
model evaluation remain necessary. `semantic_relevance_score` is null.

Templates and vocabulary were developed with the participant pack, including
its golden examples. These are development-set results, not held-out accuracy.
The generators never read expected golden questions at runtime. Unsupported
and unschedulable cases stay in coverage denominators. The evaluator explicitly
counts handoffs for golden-ineligible cases so eligibility errors are not hidden.

Source references include conditional `show_if` questions, but that property
is absent from the authoritative survey schema. We do not add it to outputs.
The v2 survey asks about one supported step, not necessarily every plan step.
For example, the mustard reference includes input access as a third item; the
v2 generic contextual survey currently covers the advised spray and reported
condition. The dedicated Radar seed-access survey is separate and unchanged.
Reference questions are preserved alongside candidates so reviewers can see
these differences rather than treating a schema pass as equivalent content.

## Run

From `farmerloop/`, with the installed environment:

```bash
python -m farmerloop.evaluate_quality
python -m farmerloop.evaluate_quality --practice --json
python -m farmerloop.demo
python -m farmerloop.feedback_demo
python -m pytest -q
```

In this Codex workspace use `/workspace/scratch/farmerloop-venv/bin/python`.
The recorded report is `../reports/survey-quality-offline.json` relative to this
file. It contains the reference/candidate pairs, reasons for held surveys,
measured timing and full-dataset summary. The CLI prints to stdout unless the
caller explicitly redirects it.

## Recorded results

Verified offline on 2026-11-04:

- **430 tests passed** (22.04 seconds), including 42 new quality tests beyond
  the 388-test Radar baseline.
- All five eligible official worked scenarios produced screened handoffs in
  both English and Hindi. The sixth scenario remained ineligible. All ten
  supplied reference surveys also passed screening; this does not establish
  equivalent question coverage or human-rated quality.
- Across the 150 golden rows, v2 produced 74 English handoffs and 73 Hindi
  handoffs. Each language includes one known eligibility false positive,
  G-0136. Coverage of the **95 golden-eligible cases** is therefore **73/95
  English (76.8%)** and **72/95 Hindi (75.8%)**. English rejected 21 generation
  attempts; Hindi rejected 22; each had one unschedulable case.
- The unchanged generic baseline produced 95 candidates per language, all
  held by the new specificity screen; one eligible case was unschedulable.
- Full English practice evaluation processed **6,999 rows**: 50 invalid,
  4,283 ineligible, and 2,666 eligible. Of the eligible rows, 1,714 produced
  screened handoffs, 916 were rejected during generation, and 36 were
  unschedulable. Coverage is 64.3% of eligible rows. The batch took 6.77 seconds;
  mean generation attempt time was 1.02 milliseconds in this environment.
- No AWS calls or model tokens were used. The JSON report records both
  candidate/reference pairs and the cases that could not produce a handoff.

Interpret the counts as follows:

- Golden eligibility remains the previously measured 149/150; quality work does
  not resolve G-0136's R7 semantic ambiguity.
- The golden set expects 95 eligible cases; our existing gate selects 96.
- Baseline surveys failing our new specificity checks do not mean Digital Green
  awarded them a 0% quality score. This is our stricter screening criterion.
- Full-window exact agreement is reported separately; following the pack's
  07:00 rule differs from the golden 09:00 convention. Dates can differ too.
  Zero exact matches must not be interpreted as a new 100% timing score.
- Offline template generation latency is not Bedrock latency. Zero model tokens
  and inference cost do not imply zero compute cost.

## Remaining requirements

This completes the approved offline quality increment, not the full Digital
Green MVP. Semantic relevance scoring, native Hindi review, expanding supported
advice patterns, crop-calendar reconciliation, weekly cap/opt-out enforcement,
REST integration, and the UI remain outstanding. The existing Radar works with
its supported seed-access template and continues through the new handoff gate.
