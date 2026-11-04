# Eligibility and timing reconciliation — participant pack v1

This checkpoint investigates the remaining eligibility mismatch and timing
disagreements. It retains the documented timing baseline, closes scheduling
bypasses, and reports conflicts explicitly. It does not claim all reference
labels are resolved or implement a semantic eligibility judge.

## Evidence and policy

- `data/participant-pack/index.html`, **The rules / When to send**: count days
  from the insight date; open at 07:00 and close at 19:00 IST; never on the
  advice day or before the action window ends; minimum two-day width; nothing
  sent after 31 March 2027. It calls `rules.json` the baseline and allows
  improvements supported by evaluation.
- `json/rules/rules.json` specifies the offset ranges and those constraints.
  Applying the constraints to the raw `same_day` and `next_day` ranges yields
  days 1–3, matching the brief's table. `seasonal` starts at day 21.
- All five eligible worked scenarios have windows exactly matching our
  existing calculation. Their survey windows open at 07:00.
- `data/golden_set.jsonl` is explicitly version 1 and may be updated by Digital
  Green. Its windows are not consistently compatible with that baseline.
- The original Digital Green Vision and Technical Word documents emphasize
  action-window and crop-calendar relevance, evaluation, and quality before
  coverage. They are available in repository commit
  `eab1f10a53ddb5b5f59dce5c83a0bb211fbd9c9d` under
  `docs/Digital Green Foundation/`; they are absent from this feature checkout.

All paths above are relative to the repository or participant pack as indicated.
The official pack was not edited. We retain its 07:00 opening and action-window
constraints rather than tune dates to the golden answers. This is a documented
project choice, not a claim of organizer approval or a perfect timing score.

## The unresolved eligibility label

G-0136 / I-006478 describes insects in **stored cauliflower**. The advice is to
clean the store, sun-dry produce again and use airtight bins. Verification is
required, resolution is `direct_action`, growth stage is **null**, and the
reference says `crop_already_harvested` (R7).

The supplied calendar puts cauliflower harvest at 5 December–10 March and
post-harvest sale at 10 December–20 March. The insight is dated 20 March; our
follow-up would begin on 25 March. That warrants review, but does not establish
when this farmer harvested or why a storage follow-up is no longer meaningful.
There is no documented rule that turns a typical calendar endpoint into an
individual storage-advice expiry.

Nine golden-eligible cases already have harvest/post-harvest stages, including
G-0125 (monitor rotting stored potatoes), G-0131 (sort and store potatoes), and
G-0139 (monitor insects in stored potatoes). G-0129 is also post-harvest
cauliflower; its expected window even extends beyond the calendar sale endpoint.
Rejecting all harvested crops, storage text, or calendar-end overruns would
therefore discard legitimate reference follow-ups. We do not special-case IDs
or invent an unverified agronomic rule to reach 150/150.

Eligibility remains **149/150**, with G-0136 explicitly reported. Clarification
needed from Digital Green: does R7 apply only to obsolete *pre-harvest* advice,
and is this storage case intentionally excluded? No message has been sent.

## Measured timing reconciliation

Run `python -m farmerloop.evaluate_timing` from `farmerloop/`; use `--json` for
every input, generated/reference window, per-constraint finding, and the
eligibility mismatch's calendar context. The saved artifact is
[`reports/timing-reconciliation.json`](../reports/timing-reconciliation.json).

Across **95 golden-eligible cases**:

| Measure | Result |
|---|---:|
| Computable windows satisfying the explicit constraints | 94/95 |
| Exact full-window matches to golden windows | 0/95 |
| Both start/end dates match (clock differences remain) | 14/95 |
| Date differences as well as possible clock differences | 80/95 |
| No feasible two-day window before season end | 1/95 |
| Golden windows satisfying the audited constraints, excluding exact boundary-clock matching | 15/95 |
| Official worked examples matching exactly | 5/5 |

Constraint findings overlap: **75** reference windows start before the action
window ends, **7** open on the advice day, **12** are narrower than two days,
and **2** extend outside sending hours. A 09:00 opening is *within* allowed
hours but differs from the specified 07:00 baseline; the report separates those
concepts. No calculated window is counted as a success when it is unavailable.

Examples:

- G-0003 has a ten-day action window. The reference opens at day 3; ours opens
  at day 10 and extends to day 12 to preserve minimum width.
- G-0009's seasonal reference opens at day 30, while rules specify day 21.
- G-0053's same-day reference closes at 19:53, beyond the 19:00 sending limit.
- G-0145 leaves only 31 March to follow up. Its reference window is ten hours
  wide. We return no feasible window instead of violating the minimum width
  or extending into April. Its *eligibility* label is still true; schedulability
  is a separate gate.

The audit covers explicit mechanical constraints, not full crop-calendar
alignment, semantic freshness, native-language quality, or agronomic correctness.
Zero exact golden matches is still zero; rule compliance is a separate measure.

## Scheduling fixes

`schedule.build_handoff` now independently checks:

1. The supplied insight passes the official input schema and eligibility gate.
2. A feasible window exists and the caller's window equals the calculation
   from that insight. Matching a tampered survey to a tampered window cannot
   bypass the timing policy.
3. The survey passes the existing quality gate and uses the same window.
4. Creation is before expiry and no later than the end of the sending window.
   The answer grace period is not permission to schedule a new delivery.
5. The complete handoff passes its supplied JSON Schema.

Timezone-aware creation strings are converted to IST, as datetime inputs already
were. Naive strings are rejected explicitly; naive datetime objects retain the
existing documented assumption that they represent IST. Schema-valid insight
timestamps must already carry +05:30. The optional practice `quality_flag` can
remain omitted in official worked examples.

## Output-contract limitation

The no-survey schema permits only `generic_information` and
`needs_more_context`. Their truthful internal equivalents are
`nothing_to_verify` and `waiting_for_details`. Junk, critical-human-call,
no-verification, season, and hypothetical R7 reasons are not disguised as
those two codes. Callers retain the explicit contract gap.

## Verification and remaining work

Regression tests cover direct eligibility bypasses, schema-invalid input,
self-consistent but altered windows, season-end infeasibility, late scheduling,
timezone conversion, documented timing offsets, reference conflicts and valid
post-harvest counterexamples. **462 tests passed** in 23.97 seconds on
2026-11-04: the prior 430 plus 32 new regression cases. Offline CLI demos and
the English/Hindi temporary UI remain functional. The JSON audit was generated
without AWS calls. A full 6,999-row English practice re-evaluation retained
1,714 screened handoffs, 916 unsupported generations, 36 infeasible windows,
4,283 ineligible inputs, and 50 invalid inputs; coverage did not silently drop
under the stronger scheduling gate.

Weekly cap and opt-out state, semantic eligibility review, calendar-aware
advice relevance, and organizer clarification remain separate next steps. The
previous survey-quality report is retained as the prior checkpoint's measurement.
The downloadable Mac ZIP is also a prior snapshot; it does not automatically
update when this checkout changes.
