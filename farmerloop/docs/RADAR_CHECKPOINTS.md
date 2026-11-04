# Regional Learning Radar — checkpoint status

## Approved scope and current state

Checkpoints 0–3 (baseline, synthetic scenario, analysis and evidence-backed findings)
are complete. The user authorized Checkpoints 1–3 and subsequently an offline survey-quality
checkpoint, documented in [SURVEY_QUALITY.md](SURVEY_QUALITY.md). The user has now
approved a basic, temporary Checkpoint 4 browser view. Checkpoint 5 remains
pending. Teammate-file edits, official-pack edits, credential changes, merges,
and paid AWS calls remain outside this scope.

Starting branch: `feature/jeremiah-farmerloop`.
Starting commit: `cd30a6e61c3d645e3d1dc7730ee0f949b635fd0c`.
Checkpoints 1–3 and the quality increment were committed and pushed with user
approval as `7de9d2b7a256e16626127eefc08a1dc9a778c343`. The temporary UI,
timing guards and development plan were subsequently saved as `c066bdf`.

The broader product context remains in [REGIONAL_LEARNING_RADAR_IDEAS.md](REGIONAL_LEARNING_RADAR_IDEAS.md).
Official schemas and rules remain authoritative in `../../data/participant-pack`.

## Checkpoint 1 implementation

The offline generator builds 60 fictional farmers, one eligible insight, one
survey, one handoff and one attempt per farmer. It reuses `decide`,
`compute_window`, `build_handoff`, survey models, `finalize_survey`, and
`simulate` → `respond.build_response`. The general offline generator and existing
modules are unchanged.

The agricultural context comes from the official wheat-variety-plan worked
example (its relative path is recorded in `source_template`). Its farmer,
conversation and insight IDs are replaced with synthetic IDs. District A and B
are fictional; neither represents actual conditions in a Bihar district.
The common context is wheat seed access, the rabi 2026–2027 season, a pre-sowing
stage (null in the official schema), and WhatsApp delivery. Every run uses one
language throughout: Hindi by default, with English also supported.

The two-question survey asks whether the farmer tried to obtain the recommended
seed, then whether seed was obtained, could not be obtained, or was not sought.
Only the explicit inability answer carries `could_not_get_input`. Not trying
does not imply an access barrier. This template is specific to the fixture;
it is not a general semantic survey generator or an agricultural quality check.

Simulation clock: advice on December 2, handoff on December 24, attempt on
December 25, expiry on December 29, cutoff December 30, 2026, all IST.
These are fixed simulated dates, not actual delivery dates or the current clock.

### Principal fixture expectations

| Count | District A | District B |
|---|---:|---:|
| Distinct due farmers/surveys | 30 | 30 |
| Distinct attempts | 30 | 30 |
| Confirmed deliveries | 27 | 15 |
| Accepted answers to barrier question q2 | 22 | 5 |
| Complete responses (including negative outcomes) | 22 | 5 |
| Explicit input-access reports | 10 | 0 |
| Delivery failures | 3 | 15 |
| Delivered but expired without an answer | 5 | 10 |

These are test expectations, not outputs of an implemented analytics engine.
The command labels them accordingly. Tests independently count generated
records and compare them with these expectations.

### Units, denominators and provenance

- `targets` records the expected due population independently of received events.
  Each entry links farmer, insight, survey and handoff identifiers.
- Response records contain delivery timestamps and outcomes for individual
  channel attempts. A separate competing delivery-record schema is unnecessary.
- Target coverage uses all 30 valid due targets per district, including those
  whose response evidence is absent or invalid.
- Barrier coverage uses an accepted q2 answer, not merely any accepted answer.
  The barrier proportion will use q2 respondents as its denominator.
- Completion uses `complete`, not `status == completed`: negative outcomes can
  be complete. A partial q1-only answer is valid feedback but cannot establish
  whether there was an input-access barrier.
- Future analysis must distinguish attempts from surveys/farmers, handle retries,
  and deduplicate exact response replays. Missing delivery evidence is unknown,
  not confirmed failure. Counting that unknown as delivered is also incorrect.
- The enclosing scenario carries synthetic labels and context. Official record
  shapes are unchanged; source IDs use `SIM-` and response keys use `sim-`.
- Hindi/English runs and variants are alternative versions of the same fixture
  and reuse IDs. Do not concatenate them as independent populations. Retain the
  scenario envelope when exporting records.

### Edge-case fixture variants

Each variant preserves all 60 targets and changes only the first A response.

| Variant | Change | Expected effect in A |
|---|---|---|
| `base` | None | Counts above |
| `replay` | Append an exact independent copy | 61 raw records overall, 60 distinct attempts; no metric inflation |
| `missing` | Remove the response | 29 evidenced attempts, 26 confirmed deliveries, 21 q2 answers, 9 barriers; one unknown target outcome |
| `malformed` | Replace `answers` with an invalid array | Same usable evidence as missing; one schema-invalid record instead of an absent record |
| `partial` | Accept q1, skip q2 | 27 deliveries, 21 q2 answers, 21 complete responses, 9 barriers; one partial response |
| `invalid_input` | Accept q1, provide unrecognized free text for q2 | Same coverage as partial, but one invalid-input response |

`malformed` intentionally violates the response schema and is labeled in the
envelope. All other generated official records pass their schemas. Checkpoint 2 now consumes these fixtures with schema rejection and deduplication.
This is a local demo analysis layer, not a production event store.

## Run

From the `farmerloop/` directory, using the environment from README setup:

```bash
.venv/bin/python -m farmerloop.radar_demo
.venv/bin/python -m farmerloop.radar_demo --language en-IN
.venv/bin/python -m farmerloop.radar_demo --variant replay
.venv/bin/python -m farmerloop.radar_demo --json
.venv/bin/python -m pytest -q
```

`--json` prints the complete envelope to stdout; default execution writes no
dataset files. Expected counts are fixture oracles and must never be used as
the source of computed analytics or UI metrics.

In this Codex workspace, the installed interpreter is
`/workspace/scratch/farmerloop-venv/bin/python`; the source directory is
`/workspace/team-41-digital-green-dc/farmerloop`.

## Verification executed in Codex (November 4, 2026)

Python 3.12.14, with dependencies already installed during Checkpoint 0:

- Full suite: **342 passed** (318 baseline plus 24 new cases).
- New tests cover both languages, all six variants, schema validation, exact
  fixture counts, identifiers, chronology, source linkage, comparable contexts,
  deterministic independent snapshots, CLI JSON, and non-barrier answers.
- New offline scenario command: exit 0, 60 targets/surveys/responses.
- Existing survey and feedback demos: exit 0; feedback still produces 20 valid
  records with source provenance and voice-to-WhatsApp fallback.
- Golden eligibility: 149/150, unchanged R7 mismatch G-0136.
- Practice ingestion: 6,949 parsed, 50 malformed/quarantined out of 6,999.
- Existing ID check: all four ID types unique across 6,999 insights.
- No live AWS calls or new package dependencies.

## Files changed

- Added `src/farmerloop/radar/__init__.py`.
- Added `src/farmerloop/radar/models.py`: scenario envelope only; no speculative analysis models.
- Added `src/farmerloop/radar/survey.py`: narrow bilingual template.
- Added `src/farmerloop/radar/scenario.py`: pipeline-based generator and variants.
- Added `src/farmerloop/radar_demo.py`: offline CLI and JSON output.
- Added `tests/test_radar_scenario.py`.
- Added this checkpoint document; linked it from the README.

## Checkpoint 2 — deterministic analysis

Added `src/farmerloop/radar/analyze.py` and `tests/test_radar_analysis.py`;
updated `radar_demo.py`, README and this document. No dependency changes.
The engine never reads `Scenario.expected`. It returns computed cohort counts,
rates with explicit numerators/denominators/units, evidence identifiers,
diagnostics, configurable thresholds and detection signals. Checkpoint 3 now adds structured narrative findings and human-review suggestions
on top of this analysis contract.

Run from `farmerloop/`:

```bash
/workspace/scratch/farmerloop-venv/bin/python -m farmerloop.radar_demo --analyze
/workspace/scratch/farmerloop-venv/bin/python -m farmerloop.radar_demo --analyze --json
/workspace/scratch/farmerloop-venv/bin/python -m farmerloop.radar_demo --variant missing --analyze
```

Without `--analyze`, the Checkpoint 1 fixture output remains available.

### Counting and rejection policies

- Valid due targets survive missing, rejected or conflicting response records.
  Invalid source/target joins are explicitly excluded with diagnostic references.
- Exact identity replays count once. Conflicting records sharing an identity are
  all excluded, irrespective of input order. Multiple keys for one
  survey/channel/attempt are conservatively treated as an attempt conflict.
- Retries increase attempt counts but not distinct target or delivered-survey
  counts. A later confirmed delivery removes a survey from unrecovered failure
  counts, while the failed attempt remains in attempt-level statistics.
- No delivery timestamp and no explicit failure means unknown, not failed.
- Accepted answers must match survey options, item results, farmer identity,
  source IDs and follow-up flags. Inconsistent chronology is rejected.
- Events recorded after the fixed cutoff are excluded. Targets not yet due do
  not enter coverage denominators. Empty denominators return null, not zero.
- Barrier answers are counted once per survey, including valid partial answers
  if q2 was accepted. Contradictory accepted q2 answers across attempts suppress
  that survey's barrier evidence and produce a diagnostic; delivery/completion
  history remains counted. Full cross-question semantic validation is not built.
- Cohorts are separated by district and agricultural context, language,
  preferred channel, survey objective/question and send window. Different
  contexts yield `not_comparable`; fewer than two cohorts yield
  `insufficient_cohorts`. `context_matched` does not mean statistically reliable.
- Counts expose distinct farmers and surveys separately. Rates use surveys or
  attempts as labeled; they do not estimate farmer-population prevalence.

Default demonstration heuristics: at least 10 barrier answers, 5 explicit
barriers and a 30% reported proportion for a barrier-pattern signal; under 50%
coverage for a blind-spot signal; at least 30% unrecovered delivery failures among
attempted surveys for a delivery warning. Fewer than 10 barrier answers produces
an insufficient-sample signal. These are configurable heuristics, not significance
thresholds. No positive-outcome conclusion is generated from zero barriers.

### Verification

**368 tests passed** on Python 3.12.14: 318 baseline, 24 Checkpoint 1 and
26 Checkpoint 2 cases. `git diff --check` passed. New cases
cover fixture variants, exact rates, independence from fixture expectations,
order invariance, conflicting identities, attempt aliases, recovery retries,
unknown delivery, malformed targets, inconsistent answers/provenance, cohort
mismatches, cutoff handling, zero denominators, small samples, configurable
thresholds, no-barrier counterexamples, resolving evidence and input immutability.

The offline analysis command computed A: 27/30 delivered, 22/30 feedback,
10/22 barriers; B: 15/30 delivered, 5/30 feedback, 0/5 barriers. It detected the
A barrier pattern and B coverage, delivery and insufficient-sample warnings.
No diagnostics were emitted for the base fixture.

## Checkpoint 3 — evidence-backed findings

Added `src/farmerloop/radar/findings.py` and `tests/test_radar_findings.py`;
updated `radar_demo.py`, README and this checkpoint record. No new dependencies,
changes to official schemas, teammate files, or existing survey/response modules.

`build_findings(scenario, thresholds)` recomputes analysis directly from source
records. It does not accept precomputed claims or use fixture expectations.
The result contains:

- Scenario identity, fixed cutoff and explicit synthetic label.
- Full analysis with thresholds, diagnostics and comparison status.
- Deterministic findings with stable IDs (within a scenario/cohort/kind), context,
  exact counts/rates, triggering signals, observations, cautious interpretation,
  evidence assessment, limitations and suggested human-review actions.
- A local evidence archive keyed by typed references such as
  `response:sim-S-...` and `insight:SIM-I-A-001`.
- Per-finding evidence roles for targets, attempts, confirmed deliveries,
  accepted barrier answers and reported barriers.
- A source chain for every contributing target linking insight, survey, handoff
  and usable response attempts. Empty attempt lists explicitly identify missing
  evidence; they do not invent absent records. Delivery and outcomes reside in
  the official response record, rather than a separate delivery schema.

`resolve_evidence(report, reference)` returns an independent source-record
snapshot or raises on an unresolved reference. These are internal references,
not web URLs. The browser UI and clickable drill-down remain Checkpoint 4.
The full JSON report carries the records needed to implement that drill-down.

The base report contains two findings:

1. District A: 10/22 respondents report inability to obtain seed; coverage 22/30.
   Suggest reviewing source reports and investigating availability/affordability
   as possible explanations, without asserting either cause.
2. District B: feedback 5/30, delivery 15/30, unrecovered failures 15/30, barriers
   0/5. Suggest reviewing delivery and feedback gaps before interpreting outcomes.
   No claim is made that zero reported barriers means better outcomes or trust.

Findings are emitted only for triggered signals, not forced to total two.
Low samples or missing feedback produce evidence-gap findings; incompatible
contexts carry an explicit comparison limitation. Null barrier rates are
explained as undefined. Conflicting source records cannot enter the evidence
archive. Diagnostic limitations refer to the whole scenario rather than
incorrectly attributing every diagnostic to a particular cohort.

The evidence assessment is `descriptive_only` or `limited`; there is no invented
probability/confidence score. Actions are marked `suggested_only`. This workflow
requires `synthetic=True` and is deliberately scoped to the demonstration.

### Run and inspect

From `farmerloop/` with an installed environment:

```bash
python -m farmerloop.radar_demo --findings
python -m farmerloop.radar_demo --findings --json
python -m farmerloop.radar_demo --findings --variant missing
```

This workspace's interpreter is `/workspace/scratch/farmerloop-venv/bin/python`.
`--findings` includes analysis and takes precedence over `--analyze`. Plain
`--json` continues to export the original scenario envelope. No command writes
files unless the caller explicitly redirects stdout.

### Verified Checkpoint 3 results (November 4, 2026)

- **388 tests passed**: all previous 368 plus 20 new Checkpoint 3 cases.
- Plain-text findings demo ran successfully with two accurate base findings.
- Hindi/English JSON CLI outputs tested successfully.
- Tests reconstruct denominators, deliveries, barriers, failures and completion
  from resolved evidence chains across all six scenario variants.
- Additional checks cover exact claims, replay invariance, conflicts, missing
  evidence, no answers, small samples, incompatible cohorts, no-barrier
  counterexamples, configurable thresholds, successful retries, deterministic
  output, input immutability and synthetic-only enforcement.
- No AWS calls, commits, pushes, merges, PRs or production integrations.

## Remaining work and next recommended task

Following the requirements review, survey quality was prioritized before UI
work. That offline increment is documented in SURVEY_QUALITY.md. Remaining core
requirements include semantic evaluation and calendar checks. Persistent cap
and opt-out enforcement is now implemented in the separate scheduler service;
see [SCHEDULER_CHECKPOINT.md](SCHEDULER_CHECKPOINT.md). Wiring it to the interactive
UI is the next checkpoint.
The subsequent eligibility/timing investigation is documented in
[DECISIONS.md](DECISIONS.md), including stricter scheduling-boundary checks and
a separate audit of contradictory reference windows. G-0136 remains unresolved.
The user subsequently approved a very simple, temporary browser demo. That
limited Checkpoint 4 view is implemented in `farmerloop/streamlit_app.py`:
one run button, English/Hindi survey selection, computed district comparison,
two readable findings, and evidence drill-down using the existing resolver.
It uses only the base synthetic scenario and keeps the existing backend intact.
Streamlit is an optional `ui` dependency. Launch instructions are in the README.
This does not include a production UI or teammate-app integration.
Verification on 2026-11-04: Streamlit's AppTest exercised the initial state,
run button, computed district counts, both findings, farmer evidence selection,
and a Hindi rerun. All checks passed; the existing suite passed 430 tests.
The running server returned HTTP 200 for the page and health endpoint. This is
functional verification, not a manual visual review in a browser.
Checkpoint 5 packages and rehearses the end-to-end presentation.

Known limits: scripted observations, fictional districts, no causal inference,
no production messaging, no persistent history in the fixed Radar viewer, no full cross-question semantic
checking, and Hindi wording still benefits from human review. The scenario
assumes one survey per farmer; cap/opt-out enforcement is tested through the
separate persistent scheduler rather than this scripted Radar scenario.
The analysis handles whole attempt records, not an event-sourced stream of
incremental updates: conflicting updates are quarantined, not reconciled.
Missing a delivery timestamp does not prove a failure. Schema validity and
these consistency checks do not establish agricultural safety or real-world
statistical validity. Cohort context is conservatively matched; season and
survey objective are trusted internal envelope metadata, not inferred from text.
