# FarmerLoop Intelligence: Milestone 1

Regional Learning Radar extension: **Checkpoints 1–3 are implemented** as an offline,
synthetic two-district scenario using the existing pipeline. Run
`python -m farmerloop.radar_demo` with the installed environment; add `--json`
for all source records. See [checkpoint status, commands, and limitations](docs/RADAR_CHECKPOINTS.md).
Add `--analyze` for computed regional metrics and detection signals, or
`--analyze --json` for the analysis contract. Add `--findings` for evidence-backed observations and human-review suggestions;
`--findings --json` includes the full source archive for drill-down. The Radar UI
is not implemented yet.

Deterministic foundation for a multilingual MEL survey agent for Digital Green's FarmerChat. It reads farmer insights, decides whether each one gets a follow-up survey, computes a send window, writes a short tap-answer survey (Hindi or English), and builds a scheduler hand-off. All emitted artifacts are checked against the supplied JSON Schemas.

## Survey quality update

The default demos now use contextual bilingual offline templates, with a fresh
quality screen before any scheduling handoff. Unsupported advice is held for
review. The original fake generator remains a comparison baseline.
Run `python -m farmerloop.evaluate_quality` for before/after screening results,
or add `--practice --json` for the full practice-run summary and reference pairs.
See [quality checks, measured results and limitations](docs/SURVEY_QUALITY.md).
These checks do not certify semantic relevance or agricultural safety.

## Setup (Python 3.12+)

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

The project reads the participant pack read-only and never writes to it. It looks for the pack in this order:

1. `FARMERLOOP_PACK`, if set.
2. `../participant-pack`, the standalone workshop layout (`/workshop/farmerloop` next to `/workshop/participant-pack`).
3. `../data/participant-pack`, the team repository layout (`farmerloop/` next to `data/participant-pack`).

`FARMERLOOP_PACK` overrides discovery directly and is used as given, without any check. The `json/schemas/` check applies only to the two automatically discovered paths: a discovered path counts only if it contains `json/schemas/`. To use a different location:

```bash
export FARMERLOOP_PACK=/path/to/participant-pack
```

## Run

```bash
.venv/bin/python scripts/smoke_load.py      # load counts + golden eligibility evaluation
.venv/bin/python scripts/verify_ids.py      # ID uniqueness across all insights
.venv/bin/python -m farmerloop.demo         # offline end-to-end demo
.venv/bin/python -m farmerloop.demo --bedrock   # one live Bedrock call, falls back to fake on error
.venv/bin/python -m farmerloop.feedback_demo    # offline simulated farmer responses (add --out to write JSON to out/feedback/)
.venv/bin/python -m pytest
```

## Modules (`src/farmerloop/`)

| Module | Purpose |
|---|---|
| `config`, `models`, `ids` | Paths, shared models, deterministic 10-digit IDs |
| `dataio`, `validate` | Read-only loaders that count failures; JSON Schema validation |
| `decide`, `evaluate` | Eligibility rules (R1 to R8) and golden-set scoring |
| `timing`, `schedule` | Send-window math (07:00 to 19:00 IST, season cutoff) and hand-off assembly |
| `generate_base`, `generate_fake`, `generate_bedrock` | Survey generation, schema gate, safety audit |
| `emit` | Builds `no_survey` only when the reason is truthfully representable, else a `ContractGap` |
| `outcomes` | Read-only lookup of `outcome_codes.json`: status, retry, cap and allowed channels per outcome |
| `respond` | Builds and validates response records from observations; derives everything else |
| `simulate`, `feedback_demo` | Deterministic simulated farmer attempts and the offline feedback demo |

## Design decisions

- Timing follows the documented 07:00 to 19:00 rule. The golden set mostly starts at 09:00; this is reported, not copied.
- Internal no-survey reasons are kept in full. Only `nothing_to_verify` and `waiting_for_details` map to the schema's two codes. Everything else becomes a `ContractGap`.
- Unparseable records are ingestion failures, not no-survey decisions.
- Survey safety checks are weak keyword heuristics that flag for review. They do not prove safety or quality. `relevance_score` is left unset.

## Milestone 1 verification (2026-11-04)

All results below are from the team-repo working copy on Python 3.12.16.

| Check | Result |
|---|---|
| `pytest` | 68 passed, 0 failed (8 test files) |
| Golden eligibility | 149/150 (99.3%), counted over all 150 rows; 0 load failures |
| Practice insights | 6,999 rows: 6,949 parsed, 50 quarantined as ingestion failures |
| Practice schema check (original JSON) | 50 of 6,999 invalid; the same 50 junk rows that fail to load |
| ID uniqueness | survey, handoff, flow key and flow UUID all unique across 6,999 insights |
| Offline demo | exit 0; survey and handoff schema-valid; junk example emitted as `ContractGap` |

Live Bedrock check: one call to `us.amazon.nova-lite-v1:0` in `us-west-2`, run with `AWS_MAX_ATTEMPTS=1` so boto3 could not retry. The call succeeded (`generated by: bedrock`, no fallback). It produced a two-question Hindi survey for insight I-000263 that passed the survey schema, the safety audit and the handoff schema. Bedrock unit tests use a mocked client and make no AWS calls.

## Checkpoint 2, batch 1: farmer feedback processing (2026-11-04)

`respond.build_response` turns one survey attempt into a response record. The caller supplies only what happened: the survey, channel, timestamps, any channel or server event, and for each question whether it was shown and the raw input the channel returned. Everything else is derived:

- answer values, interpreted from the raw input (sheet tap, button or list id, Telegram callback, keypad digit, speech or typed text) and checked against the survey's options or scale;
- status, failure code, retry decision, retry delay and cap counting, from `outcome_codes.json`;
- sheet outcome, accepted answers, completeness, the FarmerChat reply, and follow-up flags from the survey's own options and scale threshold;
- provenance (survey, farmer, source insights, language), copied from the survey.

Two kinds of invalid input are kept apart:

- **Farmer input** that matches no choice (typed text, a keypad key with no answer, unclear speech) is a normal outcome: status `invalid_input` with the channel's retry behaviour from the rules.
- **Program input** that can't be right raises `ResponseConfigError`. Examples: an unknown question, an event the channel can't produce, a button payload for another survey, or contradictory observations.

A record is `negative_outcome` only when an accepted answer carries a follow-up reason. Skipped, invalid and discarded answers never trigger follow-up.

| Check | Result |
|---|---|
| `pytest` | 318 passed, 0 failed. The 68 Checkpoint 1 tests are unchanged; 250 are new |
| Official example conformance | 208 of 208 match: 183 outcome-grid records and 25 scenario responses, every derived field compared |
| Simulator | every case the rules allow on a channel builds a valid record; forbidden pairings are rejected |
| Feedback demo | exit 0; 20 simulated records, all schema-valid, provenance checked; voice to WhatsApp fallback; no AWS calls |
| Checkpoint 1 regression | golden eligibility still 149/150; ID check and offline demo still pass |

Conformance works by rebuilding each official record from its observations alone (survey, channel, timestamps, raw inputs). The outcome event is taken from the grid file name, and only when it can't be derived. The other fields are computed and compared one by one. A mutation check confirmed the comparison detects changed status, values, results, follow-ups, replies and cap counting.

Rules not stated in `outcome_codes.json` were inferred from the outcome definitions. They match all 208 examples:

- **FarmerChat reply:**
  - `accepted` (201) when a finished attempt has accepted answers
  - `duplicate` (200) for a duplicate answer
  - `unknown_flow` (404) for a replaced survey
  - nothing for a closed survey, a wrong farmer, a retry in progress, or no accepted answers
- **Sheet outcome:** delivery failures and expiry give `never_opened`; dismissal and opt-out give `dismissed`; otherwise `finished`.

## Known limitations

- Feedback processing:
  - All response examples are Hindi (`hi-IN`), so English response records are tested only through unit tests and the simulator.
  - Not covered by any official example, so implemented from the rule definitions only: a negative answer inside a sheet closed part way, partial on app or web without a sheet event, and a flagged answer kept alongside an `invalid_input` status. In the last case the status stays `invalid_input` with `needs_follow_up` set.
  - Opt-outs are recorded but not yet enforced on future surveys. The weekly cap across several surveys is not tracked yet.
  - Duplicate, closed and replaced survey taps are passed in as events; there is no store of earlier answers that would detect them automatically.
  - Simulated records are marked by a `sim-` response key. Placeholder free text, unclear speech and the `F-SIMULATED-OTHER` identity are simulated, not real farmer data.
- R7 (`crop_already_harvested`) is not implemented. The one golden case (G-0136) cannot be told apart from valid post-harvest surveys using structured fields.
- Practice data: 50 of 6,999 insights fail the insight schema (all junk, with malformed `verification` or `advice_summary`). They are quarantined as ingestion failures, not counted as no-survey decisions.
- Historical Checkpoint 1 question-quality gaps (the new offline screen addresses some, but semantic review remains necessary): the live Bedrock survey passed the original automated checks, but review found:
  - q1 asked about two actions in one yes/no question (choosing a variety and raising the seed rate).
  - The `rationale` came back in Hindi. The schema says it should be English, but this is not enforced.
  - q2 used a yes/no-style question ("has it improved?") with better/same/worse options.
  - Minor spelling variant: "हां" instead of "हाँ" used in the worked examples.
- The safety audit is a keyword heuristic. Passing it does not prove a survey is safe or well written.
- Send windows follow the documented 07:00 start. A full window-by-window comparison with the golden set (mostly 09:00 starts) is not built yet.
- `/workshop/farmerloop` is an older backup and is not kept in sync; this team-repo copy is authoritative.
- Not built yet: Streamlit UI, Intelligence Radar, voice/TTS.
