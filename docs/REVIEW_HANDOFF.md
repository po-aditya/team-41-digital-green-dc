# Independent review hand-off

Everything below is read-only with respect to the implementation and runs
without AWS credentials, network access or paid calls. Nothing writes outside
`var/` and the pytest temp directories.

## Where

```
cd <checkout of team-41-digital-green-dc>
git branch --show-current          # work/integrated-mvp-fable (local only; never pushed)
git log --oneline fd26555..HEAD    # phase-0 base -> integrated MVP (878e2e0) -> review-1 repairs (8bb4569) -> review-2 repairs (75a09a6) -> review-3 repairs (9c79169) -> review-4 repairs
```

Participant pack (read only): `../mel-survey-agent-participant-pack/participant-pack`
(or `MEL_PARTICIPANT_PACK_DIR`). Verify it is untouched: every file is older than
this work (`find <pack> -type f -newer <pack>/README.txt | wc -l` → 0).

## Environments

- Python 3.14.4: `.venv/` (editable install from `requirements/dev.lock`).
- Python 3.12.16: `uv venv --python 3.12 /tmp/py312 && /tmp/py312/bin/pip install --require-hashes -r requirements/dev.lock -r requirements/build.lock && /tmp/py312/bin/pip install --no-deps --no-build-isolation .`

## Checks

| Check | Command | Expected |
|---|---|---|
| Full offline suite | `.venv/bin/pytest -q -p no:cacheprovider --basetemp=<dir on a large disk>` | 763 passed, 1 deselected (paid smoke test); the per-test database copies need several GB of temp space |
| Same on 3.12 | `/tmp/py312/bin/python -m pytest -q -p no:cacheprovider --basetemp=<dir>` | 763 passed |
| Dependency consistency | `.venv/bin/pip check`; `.venv/bin/pytest -q tests/test_packaging.py` | no broken requirements; locks unchanged since Phase 0 |
| App + /healthz + 6 schemas | `MEL_OPERATOR_TOKEN=<16+ chars> .venv/bin/uvicorn mel_agent.main:app --port 8765 &` then `curl -s localhost:8765/healthz` | `status ok`, 6 `schemas_loaded`, `paid_inference_enabled false` |
| Operator authorisation (live) | `curl -o /dev/null -w '%{http_code}' localhost:8765/insights` → 401; with `-H 'X-Operator-Token: <token>'` → 200; without `MEL_OPERATOR_TOKEN` set → 503 | as stated; also `tests/test_api.py` |
| Dataset integrity | `.venv/bin/python -m mel_agent --db var/r.db ingest` | 6999 lines, 50 quarantined (schema_invalid), 300 farmers, 86 calendar rows, 150 golden, csv `ok`, run status `complete` |
| Golden evaluation | `.venv/bin/python -m mel_agent --db var/r.db evaluate --out var/rep` | TP 93 / FP 0 / TN 55 / FN 2; reason codes 55/55; two explained mismatches (I-006279, I-006836) — `docs/CONTRACT_QUESTIONS.md` |
| Hindi generation | `.venv/bin/python -m mel_agent --db var/r.db evaluate --language hi-IN` | 93 generated, 0 failures, all schema-valid, all name the crop/animal |
| End-to-end demo (8 cases) | `.venv/bin/python -m mel_agent --db var/d.db demo --out var/demo` | `"all_passed": true`, exit 0, ~2 s |
| Whole dataset + season | `.venv/bin/python -m mel_agent --db var/f.db run-all --until 2027-03-31T19:00:00+05:30 --step-minutes 60` | 2628 surveys validated and scheduled (0 `pending_approval`, 0 `lost_claim`), 36 held back as `window_truncated_by_season_end`; 2651 sends, 0 `blocked_unsafe`; ~72 s with hourly ticks (3620 ticks), ~130 MB RSS |
| Persisted outputs grounded | for every `surveys.survey_json` with status `validated`: `validate_survey_text(doc, language)` is empty and every `prompt` is in `catalog.all_renderings(language)` | 2628/2628; 0 invalid hand-offs (2628) and responses (2371); `PRAGMA integrity_check` ok |
| Budget | `tests/test_budget.py`, `tests/test_regressions_codex.py::TestC1MissingUsage`, `::TestH6Ledger` | unverified usage stays unresolved; refusal at the cutoff; corrupt ledger fails closed; cross-process reservations |
| Smoke CLI gates | `tests/test_smoke_cli.py`, `tests/test_regressions_codex2.py::TestF3SmokePaths` | disabled flag, unpriced model, exhausted budget and insufficient headroom for this call all stop before credentials/AWS; the CLI and the opt-in live test only call through `BudgetedInvoker` |
| Paid retry accounting | `::TestF1TransportRetries` | paid client has SDK retries disabled and is refused otherwise; one reservation per request on the wire; `RetryAttempts>0` → unresolved; timeouts stay committed |
| Question grounding | `::TestF2GroundedQuestions` | the reviewer's antifreeze question is refused at generation and blocked at send; every catalogue rendering passes policy and schema in EN and HI; free-form only as `pending_approval`, never scheduled |
| Ledger uniqueness | `::TestF4LedgerUniqueness` | duplicate reconcile/settle/release rows rejected at insert; legacy duplicates fail closed on read; concurrent reconciliations succeed once |
| Ingestion gate | `::TestF5IngestionGateEverywhere` | single-insight path, batch, API (409) and CLI (exit 2) all refuse after a failed ingestion |
| Claim leases | `::TestF6ClaimLeases` | real-time lease with fencing token; paused worker loses the claim and persists nothing (in-process and across processes); simulated time never expires a claim |
| Script-neutral readability | `::TestF7ScriptNeutralEligibility` | Hindi/Bengali/Tamil/Kannada summaries eligible; Latin gibberish junk; pack junk count unchanged at 723 |
| Billing classification (review 3) | `tests/test_regressions_codex3.py::TestF1ErrorClassification` | ModelErrorException and every processing/unknown code stay unresolved; string or bool `RetryAttempts` is unresolved, never zero; only well-formed `RetryAttempts == 0` plus a pre-inference code releases; unresolved cap blocks new attempts and survives restart |
| Atomic ingestion | `::TestF2AtomicIngestion` | backdated failed import leaves the active dataset byte-identical and blocks generation; successful backdated import becomes current by sequence; partial staging rolls back; stuck `running` row blocks until re-run; readers never see a partial record during a concurrent import |
| Answer coverage | `::TestF3AnswerCoverage` | the reviewer's `easy/hard` and `better/same` narrowings are refused; every single omission for every intent is refused; stored hand-offs missing a required outcome or a follow-up are blocked at send |
| Client construction order | `::TestF4ClientConstructionOrder` | disabled flag, unpriced model, no headroom, unresolved cap and lost ownership perform zero client constructions; the client is built only after the reservation exists |
| No retry after supersession | `::TestF5NoRetryAfterSupersession` | a timed-out worker whose claim was taken over makes no second request; generator retries and fallback are refused once ownership is gone; an in-flight request is still settled |
| Schema migration | `::TestF6SchemaMigration` | an 8bb4569-layout database is upgraded in place (rows preserved, legacy claims taken over), repeat/concurrent startup idempotent, interrupted upgrade leaves the old version intact, duplicate ledger rows refuse the upgrade with a clear error (CLI and API) |
| Retry metadata states (review 4) | `tests/test_regressions_codex4.py::TestF1RetryMetadataStates` | missing/None/list/str envelopes, missing field, str/bool/float/negative/nested values are UNKNOWN: unresolved on errors and successes, never released or settled; repeated malformed responses accumulate committed spend and hit the unresolved cap; only a verified int 0 settles |
| Scale-question validation | `::TestF2ScaleValidation` | the reviewer's removed-follow-up and scale_min=3 documents are blocked at send; max/min/threshold/reason/options/type corruptions blocked; model-supplied scale fields ignored at construction; every scale intent definition validates |
| Pre-send ownership recheck | `::TestF3RecheckBeforeSend` | lease lost during slow client construction: no request submitted, reservation released, replacement worker untouched; applies to retries; in-flight requests still accounted |
| Schema version gate | `::TestF4SchemaVersionGate` | markers 4, 999, not-a-version, -1, 0, '', ' 3', 3.0, 03, 1e3 are refused with the marker and contents untouched (also on a legacy layout, also from the API); fresh, legacy, 1, 2, 3 open and end at 3; repeated/concurrent/interrupted starts |
| Error hygiene | `::TestF8ErrorHygiene` | unknown field names never echoed in 422s; nested non-finite numbers, deep nesting and huge arrays rejected in model JSON; 500s are generic |
| Content policy | `::TestH2UnsafeContent` | petrol/kerosene, dose quantities, URLs, bidi/zero-width, homoglyphs, advice, PII rejected in EN and HI; broadcaster blocks unsafe hand-off at send |
| Malformed model output | `::TestH3MalformedOutput`, `tests/test_generation.py::test_parse_model_json_is_strict` | `options: 7`, NaN, duplicate keys, prose-wrapped JSON → rejection path, no exception |
| Process-level concurrency | `tests/test_regressions_codex.py -k processes` | one send per hand-off / per farmer cap, one generation per insight, cutoff respected across independent processes |
| Restart recovery | `tests/test_regressions_codex.py -k Recovery` | fallback and retry markers survive a crash and are claimed once |
| Secret-disclosure regressions | `tests/test_pricing_errors.py tests/test_model_key_disclosure.py tests/test_security_mvp.py` | all pass |
| Mutation sensitivity | reintroduce any of: cutoff check, in-flight cap, quality_flag read, PII check, reject-still-schedules, earliest start day, send hours, schema quarantine, junk signature, identity check | the suite fails (10/10 verified during development) |

### Regression file against the audited baseline

```
git worktree add /tmp/base 878e2e0
cp tests/test_regressions_codex.py tests/concurrency_workers.py tests/conftest.py /tmp/base/tests/
for cls in TestC1MissingUsage TestH2UnsafeContent TestH3MalformedOutput TestH4ConcurrentCap TestH6Ledger \
           TestH7Critical TestM1Recovery TestM2Generation TestM3Ingestion TestM4Timing; do
  (cd /tmp/base && MEL_PARTICIPANT_PACK_DIR=<pack> PYTHONPATH=/tmp/base/src \
     timeout -k 10 240 python -m pytest -q -o addopts='' -rA "tests/test_regressions_codex.py::$cls")
done
git worktree remove --force /tmp/base
```

Observed: 58 tests fail, `TestM4Timing` hangs (the baseline's zero-step loop)
and `TestH4ConcurrentCap` hangs on its third test after two failures (process
contention), 16 tests pass because the baseline already met those properties
(see the docstring at the top of `tests/test_regressions_codex.py` for the
list). H1, H5 and L1 are covered in `tests/test_smoke_cli.py` and `tests/test_api.py`.

### Review-2 regression file against the audited baseline (8bb4569)

```
git worktree add /tmp/base2 8bb4569
cp tests/test_regressions_codex2.py tests/concurrency_workers.py /tmp/base2/tests/
(cd /tmp/base2 && MEL_PARTICIPANT_PACK_DIR=<pack> PYTHONPATH=/tmp/base2/src \
   timeout -k 10 800 python -m pytest -q -p no:cacheprovider tests/test_regressions_codex2.py \
   --deselect tests/test_regressions_codex2.py::TestF6ClaimLeases::test_cross_process_takeover_after_lease_expiry_yields_one_handoff \
   --deselect tests/test_regressions_codex2.py::TestF6ClaimLeases::test_live_lease_blocks_other_processes)
git worktree remove --force /tmp/base2
```

Observed on 8bb4569: 69 failed, 30 passed, 2 deselected (101 tests). Every `test_codex_reproduction_*` test fails
there. The two deselected process tests hang on the baseline (its claim API has no
lease). The baseline passes are property pins (concurrency of settle/release, the
lexical policy on free-form text, trivial malformed-shape rejections, the pack junk
count) that the repairs had to preserve.

### Review-3 regression file against the audited baseline (75a09a67)

Same procedure as above with `tests/test_regressions_codex3.py` and worktree `75a09a67`
(no deselections needed). Observed on 75a09a67: 46 failed, 20 passed (66 tests). Every
`test_codex_reproduction_*` fails there. The 20 baseline passes are property pins
(pre-inference codes were already released, timeouts already unresolved, partial
insight staging already rolled back within its own step, an in-flight call was already
settled, restart takeover already worked).

### Review-4 regression file against the audited baseline (9c791691)

Same procedure with `tests/test_regressions_codex4.py` (it imports a helper from
`tests/test_regressions_codex3.py`, so copy both) and worktree `9c791691`. Observed on
9c791691: 52 failed, 25 passed (77 tests). Every `test_codex_reproduction_*` fails
there. The 25 baseline passes are property pins (typed-but-wrong `RetryAttempts` values
were already unresolved, an untouched scale hand-off was already sent, in-flight
accounting, supported-version upgrades).

## Things to look at critically

1. `tests/test_regressions_codex.py`: one section per finding; check the probes match the equivalence classes, not just the reported strings.
2. `src/mel_agent/generation/catalog.py` + `safety.py`: the closed answer catalogue and the character/content policy are the H2 defence; the lexicons are deliberately conservative and English/Hindi only.
3. `src/mel_agent/llm/bedrock.py::parse_usage` and `llm/budgeted.py`: what counts as verified usage; the transport-retry multiplier.
4. `src/mel_agent/budget/controller.py`: Decimal ledger validation, transitions, `reconcile`.
5. `src/mel_agent/delivery/broadcaster.py::_send`: the single check-and-claim transaction; `_maybe_move_on` marker ordering.
6. `src/mel_agent/store/db.py::claim_generation` and `pipeline.py::_generate_one`: claims, collisions, no hand-off resets.
7. `src/mel_agent/rules/eligibility.py`: R2 before R1; the new incoherent-text junk signals; the held-back `window_truncated_by_season_end` decision (`docs/CONTRACT_QUESTIONS.md`).
8. `src/mel_agent/api/deps.py`: the single shared operator token and its stated production limits.
9. `src/mel_agent/generation/catalog.py::QUESTION_CATALOG`, `render_item`, `all_renderings` and `safety.py::_grounding_problems`: the review-2 question-grounding boundary. Check that no path builds a `prompt` from anything but a template plus glossary slots, and that `generation_allow_freeform` only ever leads to `pending_approval`.
10. `src/mel_agent/llm/budgeted.py`: one reservation per request on the wire; the SDK-retry refusal; the transient/permanent code sets; what `RetryAttempts` does on success and on error.
11. `src/mel_agent/store/db.py`: `ux_ledger_reservation_kind`, `ux_ledger_terminal`; `claim_generation` / `heartbeat_claim` / `finish_claim` fencing; `pipeline.py::_generate_claimed` finalises the claim before writing the survey.
12. `src/mel_agent/rules/eligibility.py::_unreadable` and `_latin_gibberish`: script-neutral floor; the documented gap for non-Latin nonsense.
13. `src/mel_agent/llm/budgeted.py` (review 3): the module docstring IS the billing policy; `classify_client_error`, the `RetryAttempts` handling (`retry_attempts_in` returns None for malformed), the operation order (ownership → reserve → client → send → settle) and `BudgetController._require_reconcilable`.
14. `src/mel_agent/data/ingest.py::run` and `store/db.py::record_ingest_run / latest_ingest_run`: one transaction for data + status, `seq` ordering, unique run ids, `insights.run_id`.
15. `src/mel_agent/generation/catalog.py`: `required` per intent, `coverage_problems`, `rendering_index`; `safety.py::_grounding_problems` applies coverage at validation and send time.
16. `src/mel_agent/store/db.py::_initialise`, `_COLUMN_MIGRATIONS`, `SCHEMA_VERSION`: the upgrade path and its refusal on duplicate ledger rows.
17. `pipeline.py::_generate_claimed::still_owner` and `generator.py::_attempt`: the ownership hook before every model invocation.
18. (review 4) `llm/bedrock.py::retry_attempts_in` three states and `InferenceResult.retry_attempts` defaulting to None; `llm/budgeted.py` step 4 (recheck after client, release, OwnershipLost); `generation/catalog.py::item_problems` (scale range, threshold, reason, type) used by `safety.py::_grounding_problems`; `store/db.py::_stored_version`, `SUPPORTED_SCHEMA_VERSIONS` and the StoreError raised before any DDL.

## Not verified (environmental)

- Docker build/run (Docker not installed on the dev machine).
- Real Bedrock output quality (no paid calls authorised); Hindi text not reviewed by a Hindi speaker.
