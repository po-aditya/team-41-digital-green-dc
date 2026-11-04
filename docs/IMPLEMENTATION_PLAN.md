# Implementation plan: remaining MVP (phases 1+)

Baseline: Phase 0 (`fd265558`), 37 files, 246 offline tests. Everything below is
added on top; Phase 0 contracts (schemas, pricing, config, secret handling) are
reused, not rewritten.

## Requirements audit (what the pack and docs ask for)

Sources: `participant-pack/index.html` (brief, contract, rules, worked scenarios,
answer simulation), `json/rules/rules.json`, `json/rules/outcome_codes.json`,
the six schemas, the Vision and Technical documents.

| # | Requirement | Source | Status in this campaign |
|---|---|---|---|
| 1 | Ingest insights, farmers, crop calendar, golden set; query by farmer/crop/topic/date | Vision "Insight ingestion" (Must) | implemented |
| 2 | Survey / no-survey decision from rules | brief "Decide survey or no survey", rules.json | implemented, deterministic |
| 3 | 1–3 tap questions in the farmer's language, no new advice, no personal info | brief, survey.schema.json | implemented (template provider; Bedrock provider behind budget gate) |
| 4 | Send window from timing + action window, 07:00–19:00 IST, ≥2 days, nothing after 31 March | rules.json `send_window_days`, `window_rules` | implemented |
| 5 | Scheduler hand-off: channel order, cap, priority, expiry, flow ids | schedule_handoff.schema.json, rules.json | implemented |
| 6 | Self-evaluation before scheduling (schema, relevance, language, safety) | Vision "Self-evaluation step" (Must) | implemented (deterministic checks; LLM-judge not run: paid) |
| 7 | Evaluation harness against the golden set | Vision (Must) | implemented |
| 8 | Scheduler + broadcaster stub on a simulated clock; frequency cap | Vision (Must/Should), Technical "Simulated Clock" | implemented |
| 9 | Simulated farmer answers incl. failures, as `response` records | brief "Simulate the farmer's answers", outcome_codes.json | implemented |
| 10 | Hindi output when language is hi-IN | Vision (Should) | implemented via templates (quality unverified by a Hindi speaker) |
| 11 | Latency and cost telemetry | Vision (Should), Technical | implemented (timings + budget ledger) |
| 12 | REST interface for operating/inspecting the agent | Technical "FastAPI" | implemented |
| 13 | Response write-back, negative-outcome routing | Vision (Exploratory) | implemented as `needs_follow_up` queue |
| 14 | Streamlit app | Technical "Streamlit or a CLI is fine" | CLI renderer instead (keeps lockfiles unchanged) |
| 15 | Real delivery, production FarmerChat integration | out of scope per Vision | not implemented (mock adapter only) |

## Golden-set rules (reverse-engineered; not documented in the pack)

The 150 golden labels carry `rule` R1..R8 and `reason_code`, but no document
defines them. Derived from the labels (all 150 consistent):

| Rule | Golden reason_code | Condition (evaluated in this order) |
|---|---|---|
| R0 | (quarantine) | fails insight.schema.json, unknown farmer, duplicate id, unknown resolution — never reaches eligibility |
| R2 | `critical_needs_human_call` | `severity == critical` — checked **before** the junk test, so a contradictory record (critical + casual) goes to a human, never to the bin |
| R1 | `junk_insight` | content signature: missing core fields, `decision_episode_type == casual`, no asset **and** no concern, or an unreadable / identical query–advice pair |
| R3 | `nothing_to_verify` | `resolution_type == generic_information` |
| R4 | `waiting_for_details` | `resolution_type == needs_more_context` |
| R5 | `no_check_needed` | actionable resolution but `verification.needed == false` |
| R6 | `window_after_season` | send window would start after 2027-03-31 |
| R6 | (`window_truncated_by_season_end`, no golden code) | the season end would cut the window below `min_width_days`; held back, see docs/CONTRACT_QUESTIONS.md §2 |
| R7 | `crop_already_harvested` | send window starts after the crop's last calendar date |
| R8 | survey | everything else |

External contract: `no_survey.schema.json` only permits `generic_information`
and `needs_more_context`. Internal reasons are kept separately; the external
code is derived: R4, R2 → `needs_more_context` (conversation still needs a
human); R1, R3, R5, R6, R7 → `generic_information`. R2 additionally lands in a
human-intervention queue. **Open question for Digital Green**: whether the
schema should grow the richer codes.

## Known contract disagreements

All open questions, with the exact affected cases and the alternatives, are in
`docs/CONTRACT_QUESTIONS.md`. Summary of the timing one:

`rules.json` reproduces all five worked scenarios exactly (07:00/19:00, start no
earlier than the action window end, ≥2 days wide). The golden set uses another
formula (09:00 start, no action-window clamp, 4-hour same-day windows,
`seasonal` as 30–45 days). We implement `rules.json` (it is the stated contract)
and report golden timing agreement separately. **Open question for Digital Green.**

## Architecture

```
src/mel_agent/
  time_utils.py         IST (+05:30) parsing/formatting, day arithmetic
  data/pack.py          participant-pack paths, rules.json / outcome_codes.json loaders
  data/ingest.py        JSONL+CSV reconciliation, farmers, calendar, golden; quarantine; stats
  store/db.py           SQLite (portable SQL) repository: insights, decisions, surveys, handoffs,
                        deliveries, responses, audit log, budget ledger
  rules/eligibility.py  R0..R8 with explicit precedence; internal vs external reason codes
  rules/timing.py       send window per rules.json; season end
  rules/scheduling.py   priority, channel order, cap, expiry, farmerchat_flow, hand-off builder
  generation/           provider protocol; template provider (en-IN, hi-IN); Bedrock provider;
                        safety checks (schema, no-advice, no-PII, injection, language)
  budget/               durable ledger + controller (reserve → call → settle; fail closed)
  delivery/             simulated clock, scheduler/broadcaster with cap + channel fallback,
                        deterministic farmer-answer simulator, bottom-sheet renderer
  pipeline.py           ingest → decide → generate → schedule → deliver, idempotent
  evaluation/           golden confusion matrix, per-rule mismatches, timing/format/relevance proxies
  api/                  read-only routers + guarded run endpoints
  cli.py                ingest / evaluate / run / demo
```

Persistence: SQLite file via stdlib `sqlite3` with PostgreSQL-compatible SQL
(no autoincrement, `ON CONFLICT`, TEXT timestamps). No new dependencies.

## Acceptance criteria and verification

- All Phase 0 tests still pass; new tests cover each module and the end-to-end flow.
- Golden eligibility confusion matrix reproducible by `python -m mel_agent evaluate` (TP 93 / FP 0 / TN 55 / FN 2; both misses are documented contract disagreements).
- `python -m mel_agent demo` runs the eight demonstration cases offline.
- Budget: reservation + cutoff + concurrency + failure tests; unverified usage stays unresolved until reconciled;
  no paid call possible unless `MEL_ALLOW_PAID_INFERENCE=true` **and** budget allows **and** a Bedrock provider
  is explicitly selected (**and** `confirm_paid` through the API).
- Operator token on every non-health route; generation claims and atomic send claims verified across processes.
- Full suite on Python 3.12 and 3.14; `/healthz`; six schemas; pack unchanged.

## Review-driven repairs (first independent review)

Thirteen findings (1 critical, 7 high, 4 medium, 1 low) were repaired on top of
`878e2e0`; `tests/test_regressions_codex.py` holds one section per finding and
`docs/REVIEW_HANDOFF.md` explains how to reproduce them, including against the
audited baseline. The notable policy change is the closed answer catalogue:
models choose option values, never farmer-visible wording.
