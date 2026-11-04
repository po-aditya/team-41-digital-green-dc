# Implementation Plan: jaak-core

## Overview

Python 3.12, new package `mel_agent/jaak/` (layout in design.md). Tasks build a thin vertical slice first so a working CLI plays a full survey as early as possible (checkpoint after task 8). Non-answer outcomes, caller events, no-advice handling, name copy, fixtures and scenario tests follow, then the optional redaction, logging and adversarial work, then the final integrity checks.

Project root: `/workshop/team-41-digital-green-dc-kevin-mockup 2/`. Paths below are relative to it.

## IMPORTANT: deferred hard requirements

Redaction (Req 17.2, 17.6, 17.7, 17.5) and logging (Req 19, plus the log-writing parts of Req 1.4, 1.6, 3.4, 3.5, 11.14, 14.7, 18.8) are hard rules of this spec. The user chose to defer them, so tasks 15 (redaction) and 16 (logging) are marked optional with `*`, and so are all property-based tests and the adversarial suite (task 17). **If those optional tasks are skipped, the engine does NOT yet satisfy those requirements.** Until they are done:

- The classifier PII rule is a pass-through hook (task 5.1), so phone numbers and volunteered personal information are not redacted.
- The engine runs with a no-op `NullLogSink` (task 1.2), so no Rejection_Log or session-end entries are written. Errors are still raised and no state changes.

## Ground rules for every task

- Do NOT edit any existing `mel_agent/*.py` module and do NOT write under `data/participant-pack/`. New code goes under `mel_agent/jaak/`, `tests/`, `tests/fixtures/jaak/` and `data/jaak/`.
- Run tests with the Python 3.12 venv from task 1.1 (local default is 3.9).
- The engine makes no free-text generation and no network calls.
- Property tests use Hypothesis with the profile from `tests/conftest.py` (at least 100 examples), tagged `# Feature: jaak-core, Property N: <text>`.

## Tasks

- [x] 1. Environment and package skeleton
  - [x] 1.1 Create dev environment and test scaffolding
    - Create `requirements-dev.txt` (new file): `-r requirements.txt`, `pytest>=8.4`, `hypothesis>=6.141`. Leave `requirements.txt` untouched.
    - Create `pytest.ini` (`testpaths = tests`) and `tests/conftest.py` with Hypothesis profiles (default `max_examples=100, deadline=None`; CI `max_examples=500, derandomize=True`).
    - Create the 3.12 venv (`uv venv --python 3.12`) and install `requirements-dev.txt`.
    - Write `tests/fixtures/jaak/mel_agent_manifest.json`: SHA-256 of every existing `mel_agent/*.py` file, taken before any jaak code exists (used by task 19.3).
    - Create empty `tests/jaak/{unit,properties,adversarial,scenarios,integration}/` packages.
    - _Requirements: 20.5, 1.8_
  - [x] 1.2 Create package skeleton, errors and null log sink
    - Create `mel_agent/jaak/__init__.py` (exports filled in task 7.1), `mel_agent/jaak/errors.py` (`JaakError`, `InputRejected`, `InvalidRequest`, `LanguageUnavailable`, `GreetingFailed`, `SurveyTextMissing`, `TemplateError`, `UnknownSession`, `SessionFinalised`, `OutOfOrder`, `NotEnded`, `TurnsPending`, `EventRejected`, `RecordInvalid`, `ConfigError`).
    - Create `mel_agent/jaak/logs.py` with the `LogSink` protocol and a no-op `NullLogSink` only. Real log builders come in optional task 16.
    - _Requirements: 20.2, 20.3, 19.6_

- [x] 2. Models and boundary validation
  - [x] 2.1 Implement Pydantic models
    - Create `mel_agent/jaak/models.py`: `Survey`, `Item`, `Option`, `SendWindow`, `ResponseRecord`, `ItemRecord`, `Timestamps`, `FarmerChatReply`, `Insight`, `NoSurvey`, `ScheduleHandoff`, `BottomSheet`, `FarmerRecord` (`extra="ignore"`), `CallTimes`, `Timeout`, `ReportFailure`, `ClosingNotDelivered`, `AnswerReceipt`, `Segment`, `Turn`.
    - Reproduce the survey `if/then/else` rules (scale vs select vs confirm, `follow_up_at_or_below` needs `follow_up_reason`); frozen where the design says so.
    - _Requirements: 1.1, 1.3, 20.1_
  - [x] 2.2 Implement boundary validators
    - Create `mel_agent/jaak/boundary.py`: validate Survey (jsonschema via `mel_agent.data.validator("survey")` then Pydantic, then exact `hi-IN`/`en-IN` check), Farmer_Record (Req 1.3), pair `farmer_id` equality, language-mismatch detection, `delivery_attempt` (int not bool, 1 to 5), Transcribed_Answer guard (str, at most 2,000 chars).
    - Return `BoundaryResult(ok, model, failures)` with failures as `(json_path, schema_keyword)`; never put library messages or values in reasons. Take a `LogSink` and call it once per rejection (works with `NullLogSink`).
    - Raise errors from `errors.py` so the engine can reject with state unchanged.
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.7, 3.4, 15.5, 18.8, 20.1, 20.7_
  - [x] 2.3 Write unit tests for models and boundary
    - File: `tests/jaak/unit/test_models_boundary.py`.
    - Every conforming pack example is accepted and every violating example rejected by both JSON Schema and Pydantic, for all six schemas.
    - Cases: 65-char `farmer_id`, blank `farmer_id`, `en-in` rejected, unsupported language rejected, pair mismatch, bad `delivery_attempt` values (0, 6, True, 2.0, "1"), non-string and 2,001-char answers.
    - _Requirements: 1.1, 1.2, 1.3, 1.7, 3.4, 15.5, 18.8_
  - [ ]* 2.4 Write property test for schema and model agreement
    - File: `tests/jaak/properties/test_p01_schema_model_agreement.py`.
    - **Property 1: Schema and model agreement**
    - **Validates: Requirements 1.1**

- [x] 3. Fixed templates and Turn rendering
  - [x] 3.1 Implement template loader/validator and en-IN templates
    - Create `mel_agent/jaak/templates.py` (`TemplateSet.load`, roles `final`/`fragment`/`closing`/`glue`, checks for markdown, emoji, sentence length 20 words with `.`, `?`, `।` terminators, URLs, identifiers, 200 chars, `?` ending on `final`, thanks and no `?` on `closing`, placeholder rules, Turn-kind sentence count 1 to 4).
    - Create `mel_agent/jaak/templates/en-IN.json` with the design's template ids and text.
    - Raise `TemplateError(template_id, rule)` at load; no partial load.
    - _Requirements: 2.2, 6.5, 6.6, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 14.3_
  - [x] 3.2 Add hi-IN templates
    - Create `mel_agent/jaak/templates/hi-IN.json` with the design's Hindi text (marked for native-speaker review in a top-level `"review_note"` key that the loader ignores).
    - _Requirements: 2.2, 3.1, 3.3, 7.1 to 7.6, 14.2_
  - [x] 3.3 Implement Turn renderer
    - Create `mel_agent/jaak/render.py`: build greeting (plain only for now), question, reask, repeat, advice_decline, reprompt and closing Turns as segment lists with `source` and `ref`; verbatim prompt/label copy; scale bounds as template slots.
    - Atomic: raise `SurveyTextMissing` for empty/missing prompt or label and `LanguageUnavailable` for a missing template language, before any state is committed.
    - The renderer takes only the validated Item, the TemplateSet, and (later) the greeting name, never Transcribed_Answer, Insight, `rationale`, `state` or `district`.
    - _Requirements: 2.1, 2.3, 5.2, 5.6, 5.7, 6.1, 6.2, 6.3, 6.4, 6.5, 6.7, 6.8, 10.7, 16.1, 16.6, 18.5_
  - [x] 3.4 Write unit tests for templates and renderer
    - File: `tests/jaak/unit/test_templates_render.py`.
    - Shipped en-IN and hi-IN sets load; greeting contains "JAAK", the FarmerChat-survey statement, at most 2 sentences, ends with the good-time question; no template asks for a name or offers a language; closings end with thanks and no question; prompt/label copied character for character incl. whitespace; option order kept; scale bounds present; empty prompt/label and missing language raise without output.
    - _Requirements: 2.2, 3.6, 4.4, 5.6, 5.7, 6.1, 6.2, 6.3, 6.7, 6.8, 7.1 to 7.7, 14.3, 17.1_
  - [ ]* 3.5 Write property test for the template validator
    - File: `tests/jaak/properties/test_p11_template_validator.py`.
    - **Property 11: Template validator rejects every violation**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7**
  - [ ]* 3.6 Write property test for question Turn structure
    - File: `tests/jaak/properties/test_p14_question_structure.py` (uses the `surveys(lang)` strategy in `tests/jaak/strategies.py`, created here).
    - **Property 14: Question Turn structure**
    - **Validates: Requirements 5.2, 5.6, 5.7, 6.3**

- [x] 4. Answer mapping
  - [x] 4.1 Implement normaliser and lexicon data
    - Create `mel_agent/jaak/normalize.py` (NFKC, casefold, zero-width strip, chandrabindu fold, whitespace collapse, trailing `. , ! ? ; : ।` strip, tokenizer on whitespace and Unicode punctuation, digit folding incl. Devanagari digits).
    - Create `mel_agent/jaak/lexicon.py` with yes/no classes (en-IN, hi-IN Devanagari and Roman) and number-word tables 0 to 10 (en, hi Devanagari, hi Roman). Phrase lists are added in tasks 10.1 and 12.1.
    - No PII logic here yet (task 15.1).
    - _Requirements: 8.2, 8.3, 9.2_
  - [x] 4.2 Implement Answer_Mapper
    - Create `mel_agent/jaak/mapper.py`: `map_select` (exact normalised label/value match, yes/no class equivalence, ambiguous gives Unclear) and `map_scale` (single distinct integer in range, non-integer/fraction/negative gives Unclear). Returns `Matched(value)` or `Unclear(reason)` only; pure and deterministic.
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 18.3, 18.7_
  - [x] 4.3 Write unit tests for the mapper
    - File: `tests/jaak/unit/test_mapper.py`.
    - Table-driven number words for every n in 0..10 in each language and script; yes/no spoken forms (haan, nahi, जी हाँ, हां/हाँ); duplicate-label ambiguity; empty, whitespace, punctuation-only; "4, four" collapses; "3.5", "three and a half", "four out of five", out-of-range, negatives; look-alike Unicode never matches.
    - _Requirements: 8.1 to 8.7, 9.1 to 9.8, 18.7_
  - [ ]* 4.4 Write property tests for select/confirm mapping
    - File: `tests/jaak/properties/test_p03_p06_select_mapper.py`; one test function per property.
    - **Property 3: Mapper closure for select and confirm Items** (Validates: 8.1, 8.5, 8.6, 18.7)
    - **Property 4: Mapper normalisation invariance** (Validates: 8.1, 8.2, 8.4)
    - **Property 5: Yes/no equivalence classes** (Validates: 8.3)
    - **Property 6: Mapper determinism** (Validates: 8.7)
  - [ ]* 4.5 Write property tests for scale mapping and injection text
    - File: `tests/jaak/properties/test_p07_p08_scale_injection.py`.
    - **Property 7: Scale mapping matches the number oracle** (Validates: 9.1, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8)
    - **Property 8: Instruction-like text never maps** (Validates: 18.1, 18.3)

- [x] 5. Session state machine (happy path plus re-ask)
  - [x] 5.1 Implement minimal classifier with redaction hook
    - Create `mel_agent/jaak/classify.py`: `classify(text, context)` returning `ANSWER(value)` when the mapper matches, otherwise `UNCLEAR`. Include a clearly named `_pii_hook(text) -> bool` that currently returns `False` (pass-through; filled by optional task 15.1) at the position of rule 3 in the design's precedence table. Later tasks add phrase classes in the design's order.
    - _Requirements: 8.1, 8.5, 18.1, 18.3, 18.5, 18.7_
  - [x] 5.2 Implement session state and happy-path transitions
    - Create `mel_agent/jaak/session.py`: frozen `SessionState`, `ItemState`; pure `step(state, input, ctx)`; phases Greeting, AwaitGreetingReply, Await per Item; greeting reply (any non-phrase reply moves to the first Item, discarded, not an attempt); `ANSWER` accepted; first `UNCLEAR` queues one `reask` (attempts 2); second `UNCLEAR` marks the Item `invalid`, value null, attempts 2; next Item or closing; last Item queues `closing_done` and ends with reason `all_resolved`.
    - Unclear text is never copied into state; only the accepted attempt's text is kept (truncated to 256).
    - Commit-on-success: `step` returns a new state, no mutation.
    - _Requirements: 2.1, 5.1, 5.2, 5.3, 5.4, 5.5, 5.10, 5.11, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 14.1_
  - [x] 5.3 Write unit tests for the state machine
    - File: `tests/jaak/unit/test_session.py`.
    - Cases: one-at-a-time order; greeting reply is not an answer or attempt; unclear then valid gives answered with attempts 2; unclear twice gives invalid with value null; re-ask Turn has only prompt, labels and templates; last Item resolved queues exactly one closing Turn and nothing after it.
    - _Requirements: 5.1 to 5.5, 5.10, 5.11, 10.1 to 10.7, 14.1_
  - [ ]* 5.4 Write property tests for ordering and ask bounds
    - File: `tests/jaak/properties/test_p15_p17_session.py` using a naive `ShadowSession` oracle.
    - **Property 15: Item order and one at a time** (Validates: 2.1, 5.1, 5.3, 5.4, 5.5, 5.10)
    - **Property 16: Ask and repeat bounds** (Validates: 10.1, 10.4, 11.1, 16.7)
    - **Property 17: Re-ask then resolve** (Validates: 10.2, 10.3, 10.5)

- [x] 6. Outcome rules and Response_Record builder
  - [x] 6.1 Implement status and follow-up derivation
    - Create `mel_agent/jaak/outcome.py`: follow-up reasons from Survey fields only (select/confirm `follow_up`, scale `follow_up_at_or_below`/`follow_up_reason`; first-occurrence order, de-duplicated, unaccepted Items add nothing, empty reason adds nothing); status precedence failure, then `negative_outcome`, then `partial`, then `completed`; `complete` iff every Item answered; success-record fields (`retry_decision` none, `retry_after_minutes` null, `counts_toward_cap` true, `farmerchat_reply` null); failure statuses discard follow-up reasons. Failure-code rows are wired in task 11.1.
    - _Requirements: 12.1, 12.2, 12.3, 12.5, 12.7, 12.9, 12.10, 13.1 to 13.10_
  - [x] 6.2 Implement Response_Record builder
    - Create `mel_agent/jaak/record.py`: build all fields per the design table (`response_key` as `rk-{survey_id}-voice-{delivery_attempt}`, `channel` voice, Survey `language`, `answers` only for answered Items, one `items` entry per Item in order, `input_kind` speech for answered Items, `raw_input` of the accepted text truncated to 256, timestamps via `mel_agent.rules.fmt_ts` with `+05:30`, `recorded_at` from the injected clock, `answered_by`, `sheet_outcome` null).
    - Validate against `data.validator("response")` and `ResponseRecord` before returning; on failure call the log sink once and raise `RecordInvalid`, returning nothing.
    - Receives no `farmer_name`, `state`, `district` or unclear text.
    - _Requirements: 1.5, 1.6, 3.7, 11.15, 12.5, 12.6, 12.9, 15.1, 15.2, 15.3, 15.4, 15.6, 15.7, 15.8, 15.9, 15.10, 15.11, 15.12, 17.4_
  - [x] 6.3 Write unit tests for outcome and record
    - File: `tests/jaak/unit/test_outcome_record.py`.
    - Status table cases (completed, partial, negative_outcome beats partial, flags on scale at/below threshold, duplicate reasons once in first-occurrence order, no reasons on unaccepted Items); `complete` flag; `response_key` determinism and length; timestamps in `+05:30` for a non-IST clock; fixed clock gives byte-identical records; fault injection: a deliberately bad record raises `RecordInvalid` and returns nothing.
    - _Requirements: 1.5, 1.6, 12.1 to 12.3, 12.5, 12.9, 12.10, 13.1 to 13.7, 15.1 to 15.4, 15.6, 15.7_
  - [ ]* 6.4 Write property tests for status and follow-up
    - File: `tests/jaak/properties/test_p25_p26_outcome.py`.
    - **Property 25: Status precedence and completeness** (Validates: 12.1, 12.2, 12.3, 12.4, 12.5, 12.9, 12.10)
    - **Property 26: Follow-up flags derive from Survey fields only** (Validates: 13.1 to 13.9, 12.7)
  - [ ]* 6.5 Write property tests for record validity and traceability
    - File: `tests/jaak/properties/test_p27_p28_record.py`.
    - **Property 27: Record is always valid and round-trips** (Validates: 1.5, 15.11)
    - **Property 28: Record traceability and determinism** (Validates: 3.7, 15.1, 15.2, 15.3, 15.4, 15.6, 15.7, 15.9, 15.10, 15.12)

- [x] 7. JaakEngine with five operations
  - [x] 7.1 Implement JaakEngine (happy path)
    - Create `mel_agent/jaak/engine.py` and fill `mel_agent/jaak/__init__.py` exports.
    - Constructor: injected `clock`, optional `log` (defaults to `NullLogSink`), `id_factory`; loads and validates both template files at construction; no session can start if loading fails.
    - Exactly five public operations: `start_session`, `next_turn`, `submit_answer(session_id, text, *, utterance_complete)`, `submit_event` (accepts `Timeout` and a stub that rejects everything else until task 11.1), `get_response`.
    - `start_session`: validate delivery_attempt, Survey, Farmer_Record, pair; warn on language mismatch via the sink; render greeting; return opaque id. `submit_answer`: ignore when `utterance_complete` is false (`AnswerReceipt.IGNORED`); `InvalidRequest` for non-str or over 2,000 chars; `OutOfOrder` when Turns are pending. `get_response`: `NotEnded`/`TurnsPending` guards; build and cache the record.
    - Commit new state only when the transition succeeds; any error leaves state unchanged.
    - _Requirements: 1.2 to 1.7, 2.1, 2.5, 2.6, 3.2, 3.5, 5.8, 5.9, 14.5, 15.4, 15.5, 18.8, 20.1, 20.3, 20.7_
  - [x] 7.2 Write unit tests for the engine happy path
    - File: `tests/jaak/unit/test_engine_happy.py`.
    - Play each shipped scenario survey (en-IN and hi-IN) with all-valid scripted answers and a fixed clock; assert Turn order, record validates, `channel` voice, language equals Survey language, no Turn after the closing Turn, premature submissions ignored with unchanged state, unknown/finalised session ids raise, public API is exactly five operations.
    - _Requirements: 2.1, 5.8, 5.9, 14.1, 14.5, 15.2, 20.3, 20.7_
  - [ ]* 7.3 Write property test for Turn provenance
    - File: `tests/jaak/properties/test_p12_turn_provenance.py` (stateful `RuleBasedStateMachine` with `take_turn`, `answer`, `premature`, `timeout`, `bad_call`).
    - **Property 12: Turn provenance**
    - **Validates: Requirements 2.4, 6.1, 6.2, 6.5, 10.7, 16.1, 16.6, 17.4, 18.2, 18.5**
  - [ ]* 7.4 Write property tests for premature calls and greeting reply
    - File: `tests/jaak/properties/test_p20_p21_engine_calls.py`.
    - **Property 20: Premature and out-of-order calls change nothing** (Validates: 5.8, 5.9, 18.8, 20.1, 20.7)
    - **Property 21: Greeting reply is neither answer nor attempt** (Validates: 5.10, 5.11)
  - [ ]* 7.5 Write property tests for delivery attempt and language
    - File: `tests/jaak/properties/test_p29_p30_params_language.py`.
    - **Property 29: Invalid delivery_attempt is rejected** (Validates: 15.5)
    - **Property 30: Language consistency** (Validates: 2.3, 3.2, 3.3, 3.5, 14.2; the warning-entry part needs optional task 16)

- [x] 8. Developer CLI
  - [x] 8.1 Implement the CLI
    - Create `mel_agent/jaak/cli.py` (`python -m mel_agent.jaak.cli run --survey PATH --farmer-id ID [--farmers-csv PATH] [--farmer-json PATH] [--name-copy PATH] [--answers FILE] [--clock ISO] [--delivery-attempt N] [--out FILE]`).
    - Interactive mode prints each Turn and reads one line per reply; blank line sends a timeout; `!drop`, `!busy`, `!noanswer`, `!expired`, `!dup`, `!mismatch ID` map to caller events once task 11.1 lands (until then they print "not supported yet"). Scripted mode reads one reply per line from `--answers` with the same directives.
    - Print the Response_Record JSON to stdout or `--out`; refuse an `--out` inside `config.PACK`; non-zero exit on any `JaakError`. Read `farmers.csv` read-only. `--name-copy` is accepted but ignored until task 13.1.
    - This is a thin wrapper over the five operations: no engine behaviour, Turn text or record fields of its own.
    - _Requirements: 20.1, 20.3, 1.8_
  - [x] 8.2 Write CLI smoke tests
    - File: `tests/jaak/integration/test_cli.py`.
    - Subprocess run in scripted mode with a fixed clock for one shipped scenario in en-IN and hi-IN; stdout record validates against `response.schema.json`; `--out` inside the pack is refused; repeated runs give identical output.
    - _Requirements: 15.7, 20.1, 20.6_

- [x] 9. Checkpoint - Working CLI plays a full survey
  - Run a full survey in both languages with the CLI (interactive once, scripted once per language) using a shipped scenario survey, and confirm the printed Response_Record validates against `response.schema.json`.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Non-answer outcomes (skip, timeout, not now, opt-out)
  - [ ] 10.1 Add phrase lists and classifier classes
    - Edit `mel_agent/jaak/lexicon.py`: opt-out, not-now, greeting-only not-now (plain no, नहीं, nahi, nahin) and skip lists for en-IN, hi-IN and Roman Hindi.
    - Edit `mel_agent/jaak/classify.py`: add `OPT_OUT`, `NOT_NOW`, `SKIP` after the mapper and PII-hook rules in the design's order; whole-utterance match only.
    - _Requirements: 5.11, 11.3, 11.4, 11.5, 18.4_
  - [ ] 10.2 Add transitions for skip, timeout, not-now and opt-out
    - Edit `mel_agent/jaak/session.py`: `SKIP` marks `skipped` and moves on; first `Timeout` re-asks (attempts 2), second marks `skipped`; greeting-reply `Timeout` moves to the first Item with no attempt; `NOT_NOW`/`OPT_OUT` at the greeting reply or any Item end with `declined`/`opted_out` and queue `closing_declined`/`closing_opted_out`, keeping accepted answers.
    - Edit `mel_agent/jaak/outcome.py` and `record.py` so the all-skipped / all-timeout / declined end reasons produce the records in the design (design assumption A3), copying `status`, `retry_decision`, `retry_after_minutes`, `counts_toward_cap` from the `voice` entry in `outcome_codes.json` (loaded through `mel_agent.data.outcome_codes()`); a `speech_not_understood` record when no Item answered and at least one `invalid`.
    - _Requirements: 5.11, 10.8, 11.1, 11.2, 11.3, 11.4, 11.5, 11.13, 11.16, 12.4, 12.8, 14.4_
  - [ ] 10.3 Write unit tests for non-answer outcomes
    - File: `tests/jaak/unit/test_non_answers.py`.
    - Skip phrase in both languages; two timeouts; timeout after unclear; not-now and opt-out at greeting reply and mid-survey keep earlier answers; plain "no" at greeting ends the session but "no" as an Item answer maps normally; decorated phrases ("skip everything now") are NOT treated as skip; closing kind matches end reason; records copy fields from `outcome_codes.json`.
    - _Requirements: 5.11, 11.1 to 11.5, 11.13, 11.16, 12.4, 14.4_
  - [ ]* 10.4 Write property test for timeout rules
    - File: `tests/jaak/properties/test_p18_timeouts.py`.
    - **Property 18: Timeout rules**
    - **Validates: Requirements 5.11, 10.8, 11.1, 11.2**
  - [ ]* 10.5 Write property tests for no-value-from-unclear and skip/decline
    - File: `tests/jaak/properties/test_p19_p23_outcomes.py`.
    - **Property 19: No value from an Unclear attempt** (Validates: 10.6, 11.16, 12.6, 16.3)
    - **Property 23: Skip, decline and opt-out phrases** (Validates: 11.3, 11.4, 11.5, 14.4, 11.16)

- [ ] 11. Caller events and failure-code records
  - [ ] 11.1 Implement caller events and failure records
    - Edit `mel_agent/jaak/engine.py`: at construction load `outcome_codes.json` and compute the voice-reportable set; implement `submit_event` for `ReportFailure(voice_call_dropped | voice_no_answer | voice_busy | window_expired | identity_mismatch(reported_farmer_id 1..64) | duplicate_answer)` and `ClosingNotDelivered`. `voice_no_answer`/`voice_busy` only before the greeting reply; codes unlisted for voice or not caller-reportable raise `EventRejected` and produce no record.
    - Edit `mel_agent/jaak/outcome.py` and `record.py`: failure-code rows copy `status`, `retry_decision`, `retry_after_minutes`, `counts_toward_cap` unchanged; accepted answers kept; empty `answers` when dropped before any Item resolved; `answered_by` set to the reported identity for `identity_mismatch`; `raw_event` fixed text truncated to 256; shown-but-unresolved Items recorded `skipped`, unseen Items `not_reached`; no closing Turn for no-live-farmer failures.
    - Edit `mel_agent/jaak/cli.py` so the `!` directives send these events.
    - _Requirements: 11.6 to 11.15, 12.8, 14.6, 14.7, 15.8, 15.10_
  - [ ] 11.2 Write unit tests for caller events
    - File: `tests/jaak/unit/test_caller_events.py`.
    - Each reportable code before and after answers; dropped before any Item gives empty `answers`; `identity_mismatch` sets `answered_by`; `keypad_out_of_range`, `farmer_declined` and `survey_closed` as events raise `EventRejected`; `voice_busy` after the greeting reply raises `OutOfOrder`; `sheet_outcome` always null; `raw_event` truncated to 256; `ClosingNotDelivered` never appears in the record.
    - _Requirements: 11.6 to 11.15, 14.6, 14.7, 15.8_
  - [ ]* 11.3 Write property tests for failure records and closing
    - File: `tests/jaak/properties/test_p24_p32_events_closing.py`.
    - **Property 24: Failure-event records come from the outcome table** (Validates: 11.6 to 11.15, 12.8, 14.6)
    - **Property 32: Closing discipline** (Validates: 14.1, 14.4, 14.5)

- [ ] 12. Hard rule: no agronomic advice
  - [ ] 12.1 Implement advice detection and repeat handling
    - Edit `mel_agent/jaak/lexicon.py`: question-form markers and advice lexicon (en-IN, hi-IN, Roman Hindi).
    - Edit `mel_agent/jaak/classify.py`: add `ADVICE` (question form and advice term) and `AMBIGUOUS` (exactly one signal) after `SKIP`, before `UNCLEAR`.
    - Edit `mel_agent/jaak/session.py`: `ADVICE` queues `advice_decline` then `repeat`; `AMBIGUOUS` queues `reprompt` then `repeat`; Item stays unanswered, `attempts` unchanged; `repeats` capped at 2 in total; at the cap a further such message marks the Item `invalid` (`speech_not_understood`) and moves on.
    - _Requirements: 16.1 to 16.8, 13.9, 10.4_
  - [ ] 12.2 Write unit tests for the no-advice rule
    - File: `tests/jaak/unit/test_no_advice.py`.
    - Agricultural questions in English, Hindi and Roman Hindi get the decline template and the same Item again; the question is never stored as an answer; ambiguous text gets the reprompt; the third such message marks the Item `invalid`; repeats do not change `attempts`; no Turn contains text from `rationale` or any Insight-like field.
    - _Requirements: 16.2, 16.3, 16.4, 16.6, 16.7, 16.8, 10.4_
  - [ ]* 12.3 Write property tests for advice handling and classifier precedence
    - File: `tests/jaak/properties/test_p09_p22_advice_precedence.py`.
    - **Property 9: Classifier precedence is fixed** (Validates: 5.11, 11.3, 11.4, 11.5, 16.2, 16.4, 18.4)
    - **Property 22: Advice and ambiguous messages repeat the Item** (Validates: 16.2, 16.3, 16.4, 16.7, 16.8)

- [ ] 13. Farmer name copy and personalised greeting
  - [ ] 13.1 Implement name copy loader and personalised greeting
    - Create `mel_agent/jaak/settings.py` (`JAAK_NAME_COPY` env, optional) and `mel_agent/jaak/names.py` (read-only loader of `farmer_id`/`farmer_name`; refuses any path inside `config.PACK`; Req 4.1 name rule: trimmed, 1 to 100 chars, at most 3 tokens, no digits, `@`, markdown, sentence punctuation or control characters; bad rows skipped).
    - Edit `mel_agent/jaak/render.py` (use `greeting_named` with a `farmer_name` segment only when a valid name exists) and `mel_agent/jaak/engine.py` (read the name once at `start_session`, then drop it from state; never pass it to the record builder). Wire `--name-copy` in `cli.py` (edit).
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 16.1, 17.4_
  - [ ] 13.2 Create the synthetic name copy
    - Create `data/jaak/farmers_named.csv` (outside `data/participant-pack/`): the columns of `farmers.csv` plus `farmer_name`, with rows only for the farmers used by the shipped scenarios (synthetic names: Devanagari for hi-IN, Latin for en-IN). Do not modify `farmers.csv`.
    - Needed for the name-copy tests and the CLI demo.
    - _Requirements: 4.1, 4.7, 1.8_
  - [ ] 13.3 Write unit tests for the name copy
    - File: `tests/jaak/unit/test_name_copy.py`.
    - None configured gives plain greeting; missing entry and blank name give plain greeting; names breaking each Req 4.1 rule (4 tokens, 101 chars, digit, `@`, markdown, sentence punctuation, control character) give plain greeting; a valid name appears exactly once in the greeting and in no later Turn; the name is absent from the record; path inside the pack is refused; the CSV file is unchanged after a call.
    - _Requirements: 4.1 to 4.7, 17.4_
  - [ ]* 13.4 Write property test for name confinement
    - File: `tests/jaak/properties/test_p31_name_confinement.py`. Turn and record assertions run now; the Rejection_Log and session-end assertions apply once optional task 16 exists.
    - **Property 31: Name confinement**
    - **Validates: Requirements 4.1, 4.3, 4.5, 4.6, 17.4, 17.5, 19.4**

- [ ] 14. Hand-written fixtures and scripted answers
  - [ ] 14.1 Write fixtures under tests/fixtures/jaak/
    - Inspect `data/participant-pack/json/scenarios/` and the shipped `survey.en-IN.json` / `survey.hi-IN.json` first; the pack ships both languages for scenarios 1 to 5, so only the extras below are hand-written (not generated or translated by the engine).
    - Create: a Survey whose `language` differs from its Farmer_Record `language`; a Survey with instruction-like text in `rationale`; a Survey with confusable and duplicate option labels; scripted-answer files `tests/fixtures/jaak/scripts/<scenario>.<lang>.json` for scenarios 1 to 5 in both languages (one all-valid run and one bad-outcome run each, with the expected status and `follow_up_reasons`); farmer fixtures needed to start sessions.
    - _Requirements: 20.6, 3.5, 18.2, 8.4_

- [ ]* 15. Redaction (deferred hard rule: Req 17.2, 17.6, 17.7)
  - [ ]* 15.1 Implement PII detection and the classifier rule
    - Edit `mel_agent/jaak/normalize.py` / `lexicon.py` (7 or more digits ignoring spaces, hyphens and a leading `+`; volunteer markers in English, Hindi, Roman Hindi; `@`; URLs) and fill `_pii_hook` in `classify.py` so it yields `UNCLEAR_REDACTED` ahead of the phrase classes.
    - _Requirements: 17.2, 17.6_
  - [ ]* 15.2 Apply redaction to the state and record
    - Edit `session.py` and `record.py`: a redacted answer is an Unclear attempt (consumes an attempt, survey continues); an accepted text that trips the PII test is stored as `[redacted]` in `raw_input`; no part of the original goes into any record field.
    - _Requirements: 17.2, 17.6, 17.7_
  - [ ]* 15.3 Write unit tests for redaction
    - File: `tests/jaak/unit/test_redaction.py`. 10-digit, spaced, hyphenated and `+91` numbers; "my name is ..." / "mera naam ..."; email and URL; session continues; two redacted answers mark the Item `invalid`.
    - _Requirements: 17.2, 17.6, 17.7_
  - [ ]* 15.4 Write property tests for redaction and no echo
    - File: `tests/jaak/properties/test_p10_p13_redaction_echo.py`.
    - **Property 10: Redaction of digit runs and volunteered personal information** (Validates: 17.2, 17.6, 17.7)
    - **Property 13: No answer echo** (Validates: 17.3, 18.6)

- [ ]* 16. Logging (deferred hard requirement: Req 19)
  - [ ]* 16.1 Implement log builders and sinks
    - Edit `mel_agent/jaak/logs.py`: Rejection_Log and session-end entry builders (whitelisted keys, boundary names from the design, absent identifiers omitted, no answer text and only lengths), `LoggingSink` (stdlib `logging`), `MemorySink`, name-scrub guard that replaces any occurrence of the session `farmer_name` and bumps a test-visible counter, fallback to the `logging` error stream when a sink raises (`logging_failed=True`).
    - _Requirements: 19.1, 19.2, 19.4, 19.6, 17.5_
  - [ ]* 16.2 Wire logging into boundary, engine, record and events
    - Edit `boundary.py`, `engine.py`, `record.py`: exactly one rejection entry per rejected Boundary (survey, farmer record, pair, answer input, call parameters, caller event, response record); one `warning` entry on language mismatch with both values; one session-end entry on the first successful `get_response` (`items_answered`, `failure_code` omitted when null, `item_failure_codes`, `closing_not_delivered` only when true).
    - _Requirements: 1.4, 1.6, 1.7, 3.4, 3.5, 11.14, 14.7, 18.8, 19.1, 19.2, 19.3, 19.5, 19.6_
  - [ ]* 16.3 Write unit tests for logging
    - File: `tests/jaak/unit/test_logging.py`. One entry per rejection with paths and reasons; identifiers absent when missing; no `farmer_name` key or value in any entry; sink that raises still rejects and flags `logging_failed`; session-end entry fields and `closing_not_delivered`.
    - _Requirements: 19.1 to 19.6, 14.7, 3.5_
  - [ ]* 16.4 Write property tests for logs and rejection
    - File: `tests/jaak/properties/test_p02_p33_logging.py`.
    - **Property 2: Invalid input is rejected whole** (Validates: 1.2, 1.3, 1.4, 1.7, 3.4, 19.1, 19.3)
    - **Property 33: Exactly one session-end log entry** (Validates: 19.5, 14.7)
    - Also extend `test_p31_name_confinement.py` with the log assertions (Validates: 19.4, 17.5).

- [ ] 17. Adversarial test suite (optional; each case runs in both languages)
  - [ ]* 17.1 Injection and survey-text abuse
    - File: `tests/jaak/adversarial/test_injection.py`. Prompt injection in answers (English, Hindi, Roman Hindi, payload plus valid label, payload inside a scale answer); instruction text in `rationale` gives identical Turns and record; requests to change language, reveal questions or skip everything leave language, order and set unchanged; Survey prompts with whitespace/newlines copied verbatim; duplicate labels give Unclear.
    - _Requirements: 18.1 to 18.6, 16.6, 6.1, 8.4_
  - [ ]* 17.2 Advice, personal-information and name-disclosure cases
    - File: `tests/jaak/adversarial/test_advice_pii_names.py`. Agricultural questions; phone numbers in several forms; "my name is ..."; email/URL; distinctive name from the name copy echoed by the farmer; name present in Survey text. Name appears only in the greeting; nothing leaks to record or logs.
    - _Requirements: 16.2, 16.7, 16.8, 17.2, 17.6, 17.7, 4.5, 4.6, 19.4_
  - [ ]* 17.3 Input-shape, ordering and event-abuse cases
    - File: `tests/jaak/adversarial/test_inputs_order_events.py`. 2,001-char and 1 MB strings, bytes, int, None, list, dict; empty/whitespace/punctuation-only answers; Cyrillic look-alikes, full-width Latin, zero-width and RTL marks, emoji; submit before greeting taken, `utterance_complete=False`, answer after closing, double `get_response`, event after finalisation, unknown ids; unlisted codes, `keypad_out_of_range`, `farmer_declined` as event, 65-char reported id, `voice_busy` after answers.
    - _Requirements: 5.8, 5.9, 8.2, 8.3, 8.5, 9.1, 11.14, 14.5, 18.7, 18.8, 20.1, 20.7_

- [ ] 18. Scenario tests
  - [ ] 18.1 Scenarios 1 to 5 in both languages (10 Response_Records)
    - File: `tests/jaak/scenarios/test_scenarios_1_to_5.py`. For each scenario and each of `en-IN`, `hi-IN`, run the scripted answers from task 14.1 (all-valid and bad-outcome runs) with a fixed clock; assert 10 records validate against `response.schema.json` with zero violations, `channel` voice, expected status and `follow_up_reasons` (scenario 4 bad path: `negative_outcome` with `could_not_reach_expert` and `crop_or_animal_damaged`); second-language fixtures are the hand-written/shipped ones, never engine-generated.
    - _Requirements: 20.6, 1.5, 12.1, 12.3, 13.1, 13.2, 15.2_
  - [ ] 18.2 Scenario 6 no_survey check
    - File: `tests/jaak/scenarios/test_scenario_6_no_survey.py`. The scenario 6 `no_survey.json` validates against `no_survey.schema.json` (JSON Schema and `NoSurvey` model) and no Dialogue_Session is started (the engine has no session for it; passing it to `start_session` is rejected at the Survey Boundary).
    - _Requirements: 20.6, 1.1_

- [ ] 19. Offline, import and integrity checks
  - [ ] 19.1 Offline test
    - File: `tests/jaak/integration/test_offline.py`. Patch `socket.socket`, `socket.create_connection`, `socket.getaddrinfo` to raise; run a full scripted session in each language with zero calls and no failures.
    - _Requirements: 20.4_
  - [ ] 19.2 Import allowlist, interface and scope checks
    - File: `tests/jaak/integration/test_imports_interface.py`. AST scan of `mel_agent/jaak/**/*.py` against the allowlist (stdlib, `pydantic`, `jsonschema`, `referencing`, `mel_agent.data`, `mel_agent.config`, `mel_agent.rules`, `mel_agent.jaak.*`); subprocess with a meta-path hook that blocks `boto3`, `botocore`, `streamlit`, `fastapi`, `uvicorn`, `pandas` and speech modules, then imports `mel_agent.jaak` and runs one session; `JaakEngine` has exactly five public operations; no LLM or free-text generator call; no function edits Survey data and Survey models are frozen.
    - _Requirements: 6.4, 16.5, 20.1, 20.2, 20.3_
  - [ ] 19.3 Participant-pack hash and existing-module checks
    - File: `tests/jaak/integration/test_integrity.py` plus a session-scoped fixture in `tests/conftest.py` (edit). SHA-256 of every file under `data/participant-pack/` (including `farmers.csv`) before and after the whole test run must be identical; `data/jaak/farmers_named.csv` is read-only to the engine; existing `mel_agent/*.py` files match `tests/fixtures/jaak/mel_agent_manifest.json`; import smoke test of `mel_agent.data`, `mel_agent.rules`, `mel_agent.config`. (This checkout has no existing test suite, so the manifest check replaces "same results before and after".)
    - _Requirements: 1.8, 4.7, 20.5_

- [ ] 20. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Requirement coverage

| Req | Covered by | Notes |
|---|---|---|
| 1 | 2.1 to 2.3, 6.2, 7.1, 19.3 | 1.4 and 1.6 log entries only in optional 16.x |
| 2 | 3.1 to 3.4, 5.2, 7.1 | |
| 3 | 3.2, 7.1, 6.2, 18.1 | 3.4 and 3.5 log entries only in optional 16.x |
| 4 | 13.1 to 13.3 | |
| 5 | 5.2, 7.1, 10.2 | |
| 6 | 3.3, 3.4, 19.2 | |
| 7 | 3.1, 3.4 | |
| 8, 9 | 4.1 to 4.3 | |
| 10 | 5.2, 5.3, 10.2 | |
| 11 | 10.2, 11.1, 11.2 | 11.14 log entry only in optional 16.x |
| 12, 13 | 6.1 to 6.3, 10.2 | |
| 14 | 5.2, 10.2, 11.1 | 14.7 log indicator only in optional 16.x |
| 15 | 6.2, 6.3, 7.1 | |
| 16 | 12.1, 12.2, 3.3, 19.2 | |
| 17 | 3.3, 6.2 (17.1, 17.3, 17.4 in core); **17.2, 17.5, 17.6, 17.7 only in optional tasks 15 and 16** | Not satisfied if skipped |
| 18 | 4.2, 5.1, 7.1, 10.1 | 18.8 log entry only in optional 16.x |
| 19 | **Only in optional task 16** | Not satisfied if skipped |
| 20 | 7.1, 7.2, 8.x, 18.x, 19.x | |

Property tests (all optional) cover Properties 1 to 33: P1 (2.4), P2 (16.4), P3 to P6 (4.4), P7 and P8 (4.5), P9 and P22 (12.3), P10 and P13 (15.4), P11 (3.5), P12 (7.3), P14 (3.6), P15 to P17 (5.4), P18 (10.4), P19 and P23 (10.5), P20 and P21 (7.4), P24 and P32 (11.3), P25 and P26 (6.4), P27 and P28 (6.5), P29 and P30 (7.5), P31 (13.4, 16.4), P33 (16.4).

## Notes

- Tasks marked with `*` are optional. Tasks 15 (redaction), 16 (logging) and 17 (adversarial suite) are optional as a whole; their parents are not starred because only sub-tasks may carry `*`.
- Unit tests for core behaviour, the CLI, boundary validation, template validation, answer mapping, status/follow-up derivation, failure-code records, the no-advice rule, the name copy, scenario tests, and offline/import checks are NOT optional.
- Each task names the files it creates or edits; do not touch existing `mel_agent` modules or `data/participant-pack/`.
- Hindi templates (task 3.2) need native-speaker review before real use.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "3.1", "4.1"] },
    { "id": 3, "tasks": ["2.2", "3.2", "4.2"] },
    { "id": 4, "tasks": ["2.3", "3.3", "4.3"] },
    { "id": 5, "tasks": ["3.4", "5.1", "6.1"] },
    { "id": 6, "tasks": ["5.2", "6.2"] },
    { "id": 7, "tasks": ["5.3", "6.3", "7.1"] },
    { "id": 8, "tasks": ["7.2", "8.1"] },
    { "id": 9, "tasks": ["8.2"] },
    { "id": 10, "tasks": ["10.1", "14.1"] },
    { "id": 11, "tasks": ["10.2"] },
    { "id": 12, "tasks": ["10.3", "11.1"] },
    { "id": 13, "tasks": ["11.2", "12.1"] },
    { "id": 14, "tasks": ["12.2", "13.1", "13.2"] },
    { "id": 15, "tasks": ["13.3", "18.1", "18.2"] },
    { "id": 16, "tasks": ["19.1", "19.2", "19.3"] },
    { "id": 17, "tasks": ["2.4", "3.5", "3.6", "4.4", "4.5", "5.4", "6.4", "6.5", "7.3", "7.4", "7.5", "10.4", "10.5", "11.3", "12.3", "13.4", "15.1", "16.1"] },
    { "id": 18, "tasks": ["15.2", "16.2"] },
    { "id": 19, "tasks": ["15.3", "15.4", "16.3", "16.4"] },
    { "id": 20, "tasks": ["17.1", "17.2", "17.3"] }
  ]
}
```
