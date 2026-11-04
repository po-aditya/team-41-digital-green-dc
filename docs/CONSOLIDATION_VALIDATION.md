# Consolidation validation

Verified independently on 4 November 2026, using CPython 3.12.16 and a temporary
virtual environment. This is a local review branch; `main` and GitHub have not been
updated by the consolidation. No live model calls or real farmer deliveries were
made. The participant data is synthetic.

## Automated checks

| Check | Result |
|---|---|
| Primary phased MVP, including seven new workspace regressions | 770 passed; one opt-in paid Bedrock test deselected |
| Kevin prototype, including authentication and paid-call regressions | 57 passed |
| FarmerLoop, including official response-example conformance | 318 passed |
| Interactive briefing, offline Chrome at desktop/mobile sizes | 22 passed; no external requests or browser errors |
| Primary offline demo | All eight cases passed |
| FarmerLoop offline demo and feedback demo | Exit 0; 20 response records schema-valid; provenance checked |
| FarmerLoop full-data identifier check | All 6,999 source IDs and each derived identifier unique and pattern-valid |
| Source preservation | Every unique tracked blob across the pinned source branches accounted for; declared modifications documented in manifest |
| Uploaded documents | Both substantive Word documents byte-identical to the pinned original commit; readable document XML |

The tests were created before the corresponding consolidation and security
changes. An initial primary-suite run had ten failures because the temporary
environment had dependencies but lacked an editable installation; subprocess tests
intentionally remove `PYTHONPATH`. Installing the local package as documented
resolved all ten. The final complete suite passed without deselecting failed tests.
The briefing browser initially could not start inside the filesystem sandbox;
its unchanged acceptance runner passed after an approved external Chrome launch.

## New full-data template run

The [complete run](validation/primary-full-season.json) used a fresh temporary
SQLite database, deterministic templates, a simulated season from 1 November 2026
through 5 April 2027, and three-hour ticks. It did not overwrite historical model
reports. Generation accepted all 2,628 eligible insights in 8.251 seconds; this is
local template performance, with no model token usage or inference cost.

| Measure | Result |
|---|---|
| Input insights | 6,999 |
| Valid insights / quarantined malformed insights | 6,949 / 50 |
| Accepted surveys and scheduler handoffs | 2,628 each |
| Rejected surveys | 0 |
| Simulated send attempts | 2,643 |
| Answered handoffs / cap-suppressed handoffs | 1,436 / 571 |
| Stored response records | 2,372 |
| Negative outcomes / records flagged for follow-up | 527 / 527 |

A separate [database audit](validation/full-season-audit.json) revalidated every
stored survey, handoff and response against the six unchanged official schemas:
zero invalid documents. Every negative-outcome response carried the follow-up flag.
For 1,770 non-exempt first sends, the audit compared prior send order and stored
counted timestamps within each farmer's trailing cap window: zero violations.
Retries and explicitly exempt sends were not subjects of this cap check. The unit
suite separately covers in-flight cap reservation and process/thread concurrency.
This audit does not establish delivery guarantees for a real channel provider.

## Golden-set results and limits

The primary [new golden evaluation](validation/primary-golden-evaluation.json)
scored 148 of 150 eligibility decisions correctly: 93 true positives, 55 true
negatives, no false positives, and two false negatives. The two misses reflect
already documented season-end and action-window contract disagreements.

Timing agreement is materially weaker: only 14 of 93 generated windows match both
golden dates exactly; 86 of 93 overlap. Follow-up timing remains a policy question
for Digital Green, as described in `docs/CONTRACT_QUESTIONS.md`. Eligibility
accuracy is not proof of question quality, semantic relevance or Hindi fluency.
The primary evaluation uses deterministic templates and automated proxies.

Kevin's new rules-only run scored 150/150 decisions, rules and exact windows.
It judged zero generated surveys: no current relevance, safety or model latency
measurement is implied. Its historical model-based reports remain historical
branch evidence. FarmerLoop's smoke evaluation remained 149/150; the unimplemented
harvest rule is documented in its README. The three policies differ, so these
figures cannot select a winner by themselves.

## Reproduction

Install Python 3.12+ and use a disposable environment:

```sh
uv venv --python 3.12 /private/tmp/team41-test-venv
uv pip install --python /private/tmp/team41-test-venv/bin/python --require-hashes -r requirements/dev.lock
uv pip install --python /private/tmp/team41-test-venv/bin/python --no-deps -e .
PYTHONPATH=src MEL_ALLOW_PAID_INFERENCE=false /private/tmp/team41-test-venv/bin/python -m pytest -q tests
PYTHONPATH=farmerloop/src MEL_ALLOW_PAID_INFERENCE=false /private/tmp/team41-test-venv/bin/python -m pytest -q -c farmerloop/pyproject.toml farmerloop/tests
PYTHONPATH="$PWD/prototypes/kevin" MEL_ALLOW_PAID_INFERENCE=false /private/tmp/team41-test-venv/bin/python -m pytest -q -c /dev/null --rootdir=prototypes/kevin prototypes/kevin/tests
PYTHONPATH=src MEL_ALLOW_PAID_INFERENCE=false /private/tmp/team41-test-venv/bin/python -m mel_agent --db /private/tmp/team41-new-run.db --clock 2026-11-01T00:00:00+05:30 run-all --until 2027-04-05T00:00:00+05:30 --step-minutes 180
node tests/briefing.acceptance.mjs
```

The browser runner uses the desktop's bundled Playwright and installed Chrome;
other machines need a corresponding Playwright runtime. The integration tests
read pinned Git objects, so source commits must remain reachable in repository
history. Docker packaging checks are static; no container image was built or run.
The Streamlit prototype was not launched. No production integration or human
Hindi/agronomy review is claimed.

[One-time local document hash evidence](validation/local-document-preservation.json)
records that the user's untracked vision text was preserved. Future user edits to
that local file are intentionally not constrained by the regression tests.
