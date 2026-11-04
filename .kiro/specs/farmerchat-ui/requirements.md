# Requirements Document

## Introduction

This document specifies the requirements for **farmerchat-ui**, the React + TypeScript + Vite front end for Team 41's AWS hackathon entry: the Digital Green **FarmerChat Contextual MEL Survey Agent**. The front end lives in `/frontend` and is a single-screen demo built for a 1440x900 projector.

The UI is a split screen: a LEFT **operator console** (~62% width) and a RIGHT **farmer phone simulator** (~38% width), tied together by a shared **simulated clock**, plus **JAAKBOT**, a browser-only voice assistant available on both sides. The demo must let a judge watch one insight flow end to end — ingested, a decision made, a survey generated, scheduled against a crop calendar, delivered to a simulated phone, answered (by tap or voice), and — when the answer is negative — immediately surfaced as a follow-up case.

The UI's credibility is the product. Every value a judge sees must trace to the participant pack, a real backend run, or the `reports/` directory. Three steering files already govern this work and are binding: **design-tokens** (one green visual language, tokens only, WCAG AA), **safety-and-honesty** (never overclaim; persistent synthetic/simulated badge; honest provenance; JAAKBOT guardrails; security), and **never-invent-data** (no hand-written fixtures; label anything without a backend endpoint; show "not shown here" for brief numbers absent from this repo). These are referenced throughout and are not restated in full.

The backend (`mel_agent`, FastAPI) behaviour is frozen. The front end builds exclusively on its five verified endpoints, the participant pack, and the `reports/` files. Capabilities that have no backend endpoint in this repo are presented as simulated-in-UI and labelled as such; brief numbers that are absent from this repo are shown as "not shown here" rather than displayed as fact.

## Glossary

- **UI**: The farmerchat-ui React application (the system this document specifies), served from `/frontend`.
- **Operator_Console**: The left pane (~62%), the MEL operator's view: pipeline, timeline, drawers, queues, clock, Evidence.
- **Phone_Simulator**: The right pane (~38%), a CSS device frame simulating the farmer's FarmerChat experience across channels.
- **Simulated_Clock**: A UI-only IST clock and season scrubber (Nov–Mar). There is no backend clock endpoint; all time advancement and resulting diffs are computed in the UI.
- **JAAKBOT**: A fresh browser-only TypeScript voice assistant. It has a farmer-side mode (the pack Voice channel as a state machine) and an operator-side mode (a fixed command grammar). It uses no LLM and never gives advice.
- **DataSource**: The UI's data abstraction with three implementations: Live_Api_Source, Pack_Source, Fixture_Source.
- **Live_Api_Source**: DataSource backed by the five real `mel_agent` endpoints.
- **Pack_Source**: DataSource backed by participant-pack artifacts copied into `public/fixtures`.
- **Fixture_Source**: DataSource backed by a seeded slice of a real offline backend run, covering states the scenarios lack.
- **Backend_API**: The `mel_agent` FastAPI service. Verified endpoints only: `GET /health`, `POST /v1/surveys`, `GET /v1/surveys/{survey_id}`, `POST /v1/surveys/{flow_id}/responses`, `GET /v1/follow-ups`.
- **Participant_Pack**: The dataset at `data/participant-pack/` (rules, six JSON Schemas, six scenarios, outcome fixtures, insights.jsonl, golden_set.jsonl).
- **Reports**: The `reports/v0..v4` JSON files (improvement iterations over the golden set of 150 cases).
- **Insight**: An input record describing a FarmerChat advice event for one farmer, validated by `insight.schema.json`.
- **Survey**: A generated MEL survey (items with fixed options and follow-up codes), validated by `survey.schema.json`.
- **No_Survey**: A decision to NOT survey, validated by `no_survey.schema.json` (e.g. generic_information, needs_more_context).
- **Schedule_Handoff**: The scheduling/channel/window record, validated by `schedule_handoff.schema.json`.
- **Response_Record**: A farmer's answer record, validated by `response.schema.json`.
- **Render_Artifact**: A per-channel, per-language render file at `render/{lang}/{channel}.json` (app, web, whatsapp, telegram, voice).
- **Bottom_Sheet**: The app/web presentation shape (`bottom_sheet.schema.json`): one question per step, backend step labels, skip/close/swipe-down, backend thank-you.
- **Decision_Rules**: The eligibility, window, priority, channel and cap rules in `json/rules/rules.json`. (The "R0–R8" labels in the brief are a UI display convention; see Assumptions.)
- **Outcome_Codes**: The simulated delivery/answer outcomes in `json/rules/outcome_codes.json` (e.g. completed, partial, sheet_dismissed, push_not_opened, silent, keypad_out_of_range, wa_undelivered, voice_no_answer, duplicate_answer).
- **Follow_Up_Case**: A record derived from a negative or failed outcome, exposed by `GET /v1/follow-ups` and shown in the console.
- **Provenance_Chip**: A visible indicator of generation provider ("template, offline" vs "Bedrock") and paid-inference status.
- **Synthetic_Badge**: The persistent, non-dismissable "SYNTHETIC DATA · SIMULATED DELIVERY" badge required by the safety-and-honesty steering.
- **Money_Moment**: The sub-20-second scripted sequence (advance clock → row lights → push → tap → Hindi sheet rises → negative answer → celebration → follow-up case appears).
- **DSF2**: The 1440x900 projector target used for screenshot comparison against the reference image.

## Requirements

### Requirement 1: Split-screen shell, honesty chrome, and responsive layout

**User Story:** As a MEL operator demoing to judges, I want a split-screen shell with always-on honesty indicators and a Hindi toggle, so that the audience sees the whole flow and is never misled about provenance.

#### Acceptance Criteria

1. THE UI SHALL render the Operator_Console at approximately 62% width and the Phone_Simulator at approximately 38% width on a 1440x900 viewport.
2. THE UI SHALL display the Synthetic_Badge reading "SYNTHETIC DATA · SIMULATED DELIVERY" persistently, and THE UI SHALL provide no control that dismisses the Synthetic_Badge.
3. THE UI SHALL display a data-source chip identifying the active DataSource as one of Live_Api_Source, Pack_Source, or Fixture_Source.
4. THE UI SHALL display a Provenance_Chip identifying the generation provider as "template, offline" or "Bedrock" for the active survey, and THE UI SHALL NOT present template output as Bedrock output.
5. WHEN the operator selects the Hindi option on the farmer-view language toggle, THE UI SHALL render the Phone_Simulator content in hi-IN; WHEN the operator selects the English option, THE UI SHALL render the Phone_Simulator content in en-IN.
6. WHILE the viewport width is below 1100px, THE UI SHALL stack the Operator_Console and Phone_Simulator into separate tabs labelled "Console" and "Phone".
7. WHILE the Phone_Simulator is rendered at 360px width, THE UI SHALL display Hindi text without clipping.

### Requirement 2: DataSource abstraction with three sources and auto-fallback

**User Story:** As a developer, I want a single data abstraction with live, pack, and fixture implementations and graceful fallback, so that the demo runs identically on the real API or offline.

#### Acceptance Criteria

1. THE UI SHALL expose a DataSource abstraction implemented by Live_Api_Source, Pack_Source, and Fixture_Source.
2. THE Live_Api_Source SHALL call only the five verified Backend_API endpoints.
3. WHERE an operator token is required, THE Live_Api_Source SHALL hold the token in memory only and SHALL NOT write the token to localStorage, the URL, logs, or the repository.
4. WHEN a Live_Api_Source request fails to reach the Backend_API, THE UI SHALL switch to Fixture_Source and SHALL display a visible fallback banner stating that fixtures are in use.
5. THE UI SHALL provide a manual control to switch the active DataSource.
6. WHILE a DataSource request is in progress, THE UI SHALL display a loading state; WHEN a request returns no records, THE UI SHALL display an empty state; IF a request returns an error, THEN THE UI SHALL display an error state with a retry control.
7. THE UI SHALL cap list rendering at 200 records per page and SHALL provide pagination for larger collections.
8. WHEN a new request supersedes an in-flight request for the same resource, THE UI SHALL cancel the in-flight request.
9. THE UI SHALL cache DataSource reads and SHALL refetch affected queries after a write action, and THE UI SHALL NOT poll the Backend_API on a timer.

### Requirement 3: Fixture generation and schema validation

**User Story:** As a developer, I want fixtures generated from the pack and a real backend run and validated against the pack schemas, so that no value is hand-written and the real dataset is a drop-in.

#### Acceptance Criteria

1. WHEN the developer runs `npm run fixtures`, THE UI SHALL generate fixture artifacts from the Participant_Pack and from a real offline Backend_API run.
2. THE UI test suite SHALL validate every generated survey, Response_Record, and Schedule_Handoff artifact against the six Participant_Pack JSON Schemas.
3. IF a generated artifact fails validation against its schema, THEN THE fixture validation test SHALL fail.
4. THE UI repository SHALL document, in the README, the procedure to replace fixtures with the real dataset or point at the live Backend_API without UI code changes.

### Requirement 4: Simulated clock and advancement diff

**User Story:** As an operator, I want a simulated IST clock with a season scrubber that produces a diff when I advance time, so that I can demonstrate scheduling and expiry without a backend clock.

#### Acceptance Criteria

1. THE UI SHALL display the Simulated_Clock in IST and SHALL label it "simulated in UI, no backend endpoint".
2. THE UI SHALL provide a season scrubber spanning November through March and controls to step the Simulated_Clock by +1 hour, +1 day, and +1 week, and to jump to the next due survey.
3. WHEN the operator advances the Simulated_Clock, THE UI SHALL compute a diff card in the UI from Schedule_Handoff send windows, the frequency cap, the 31 March season end, and the Outcome_Codes fixtures.
4. THE diff card SHALL classify each affected survey as delivered, deferred-by-cap, or expired.
5. THE diff card SHALL display the count of surveys blocked as unsafe as 0.
6. THE UI SHALL NOT claim that the Simulated_Clock reads from or writes to the Backend_API.

### Requirement 5: Pipeline strip with decision explainability

**User Story:** As an operator, I want a pipeline strip showing Ingest→Answer with counts and a plain-language reason for each decision, so that judges understand how the agent decides.

#### Acceptance Criteria

1. THE UI SHALL render a segmented progress strip with the stages Ingest, Decide, Generate, Schedule, Deliver, and Answer.
2. THE UI SHALL display per-stage counts sourced from the active DataSource, and THE UI SHALL distinguish valid ingested insights from quarantined insights.
3. THE UI SHALL display, for a selected insight's Decide stage, which Decision_Rule fired, expressed in plain language from `rules.json`.
4. WHEN the operator triggers Generate for one insight, THE UI SHALL call `POST /v1/surveys` with that insight and SHALL render the returned decision, survey, and handoff.
5. WHILE a run is in progress, THE UI SHALL disable the run controls, and repeated triggering of the same run SHALL be idempotent.
6. WHERE a count represents batch activity for which no Backend_API endpoint exists, THE UI SHALL label that count as fixtures or simulated.

### Requirement 6: Survey timeline with state chips and filters

**User Story:** As an operator, I want a filterable, virtualized survey timeline with clear state chips, so that I can scan thousands of surveys and find the one to demo.

#### Acceptance Criteria

1. THE UI SHALL display surveys in a timeline of lanes or a table, each row carrying a state chip.
2. THE UI SHALL support the state chips scheduled, due, deferred-by-cap, delivered, answered, expired, and held-back, and THE UI SHALL distinguish the held-back reasons window_truncated_by_season_end and crop_already_harvested.
3. THE UI SHALL provide filters by crop, topic, language, channel, severity, and state.
4. WHILE more than 200 surveys are present, THE UI SHALL virtualize the timeline so that rendering remains responsive.
5. THE UI SHALL convey every state using an icon and a text label and SHALL NOT convey state by colour alone.

### Requirement 7: Survey detail drawer

**User Story:** As an operator, I want a detail drawer that shows the full trace of one survey, so that I can prove each value against its source.

#### Acceptance Criteria

1. WHEN the operator opens a survey detail drawer, THE UI SHALL display the source Insight linked to the survey.
2. THE UI SHALL display the decision and, for a No_Survey outcome, SHALL display the internal and external no_survey reason codes.
3. THE UI SHALL display the survey items, their fixed options, and their follow-up codes as returned by the Backend_API.
4. THE UI SHALL display the validation and self-evaluation report derived from the `POST /v1/surveys` result.
5. THE UI SHALL display a send-window mini-timeline positioned against the crop calendar and the 31 March season end.
6. THE UI SHALL display the channel order and its rationale, the priority, the frequency cap state, and the expiry.
7. THE UI SHALL display the Provenance_Chip and the delivery attempts for the survey.
8. WHERE a Response_Record exists for the survey, THE UI SHALL display its answers, status, failure_code, retry_decision, needs_follow_up flag, and follow_up_reasons.
9. THE UI SHALL provide a bidirectional link between the survey and its source Insight.

### Requirement 8: Follow-up and human queues

**User Story:** As an operator, I want a follow-up queue from the API and a clearly simulated human-review queue, so that negative outcomes and critical insights are visible without the UI ever giving advice.

#### Acceptance Criteria

1. THE UI SHALL populate the follow-up queue from `GET /v1/follow-ups` and SHALL display a reason chip for each follow_up reason.
2. THE UI SHALL display a human queue of critical insights routed to a person, sourced from fixtures or the pack, and SHALL label the human queue "simulated in UI, no backend endpoint".
3. WHEN the operator changes a human-queue item's status, THE UI SHALL apply the change locally and SHALL label the view a "simulated reviewer view".
4. THE UI SHALL offer only a fixed-template acknowledgement for queue items and SHALL NOT generate agronomic, veterinary, or health advice.

### Requirement 9: Phone simulator and channel rendering

**User Story:** As a judge, I want a realistic FarmerChat phone that renders each channel exactly from the backend, so that the simulated delivery is credible and honest.

#### Acceptance Criteria

1. THE Phone_Simulator SHALL display a CSS device frame with a 9:41 status bar and a home pill, and SHALL display a FarmerChat-style chat containing the insight's advice message, a push notification, and a Bottom_Sheet.
2. THE Phone_Simulator SHALL provide a farmer selector showing name, district, crop, and language, and a shortcut to the next-due survey.
3. WHEN the operator switches the channel to App, Web, WhatsApp, Telegram, or Voice, THE Phone_Simulator SHALL render exactly from the corresponding `render/{lang}/{channel}.json` Render_Artifact.
4. THE Bottom_Sheet SHALL present one question per step, SHALL use the backend `step_label`, SHALL offer skip, close, and swipe-down-to-close, and SHALL display the backend `thank_you`.
5. THE Phone_Simulator SHALL present the Bottom_Sheet `opens_when` and `waits_for` values as a tooltip.
6. THE Phone_Simulator SHALL render Hindi text verbatim from the Backend_API using Noto Sans Devanagari, SHALL mark UI-chrome dictionary strings "needs native-speaker review", and SHALL render Hindi without clipping at 360px width.

### Requirement 10: Tap handling and write-back

**User Story:** As an operator, I want taps persisted when a flow exists and clearly simulated otherwise, and a behaviour replay, so that answers, retries, and follow-ups are demonstrable and honest.

#### Acceptance Criteria

1. WHEN a farmer taps an answer and a flow exists for the survey, THE UI SHALL persist the answer via `POST /v1/surveys/{flow_id}/responses`.
2. IF no flow exists for the survey, THEN THE UI SHALL simulate the answer locally using pack responses and Outcome_Codes and SHALL label it "simulated tap, not persisted".
3. WHEN the operator activates "Simulate farmer behaviour", THE UI SHALL replay the Outcome_Codes grid and SHALL display each outcome's retry_decision, retry_after_minutes, and counts_toward_cap.
4. WHEN a farmer submits a negative answer, THE UI SHALL create a Follow_Up_Case in the Operator_Console without further operator action.
5. THE UI SHALL produce Response_Records from a voice answer and a tap answer that differ only by the `input_kind` field.

### Requirement 11: JAAKBOT farmer-side voice (pack Voice channel)

**User Story:** As a farmer or demo driver, I want JAAKBOT to run the Voice channel strictly from the render file with keypad, real speech, and simulated-speech inputs, so that the voice flow is deterministic, safe, and accessible.

#### Acceptance Criteria

1. THE JAAKBOT farmer-side mode SHALL run as a state machine strictly from the Voice Render_Artifact, covering ringing, opening, per-item say-and-wait with `timeout_seconds`, `repeat_if_no_input` once, and closing or `closing_if_follow_up`.
2. WHEN two consecutive prompts receive no input, THE JAAKBOT farmer-side mode SHALL end the call and SHALL save answers so far as a partial Response_Record.
3. THE JAAKBOT farmer-side mode SHALL provide three always-available inputs: an on-screen DTMF keypad from the render keypad map, the Web Speech API for hi-IN and en-IN where the browser supports it, and a "Simulate speech" chip row built from the render `speech` synonyms.
4. THE JAAKBOT farmer-side mode SHALL match input deterministically against only the current item's synonyms and keypad digits, and SHALL NOT accept free-generated answers.
5. IF an input matches no synonym or digit for the current item, THEN THE JAAKBOT farmer-side mode SHALL issue a polite re-prompt and SHALL count that re-prompt toward the silent-prompt budget.
6. WHEN an input is matched, THE JAAKBOT farmer-side mode SHALL confirm by reading back the matched option label.
7. THE JAAKBOT farmer-side mode SHALL display captions and a listening indicator whenever it is listening, and SHALL use speechSynthesis for text-to-speech with a caption fallback when speech is unavailable.
8. THE UI SHALL make the JAAKBOT farmer-side voice path available inside the app Bottom_Sheet via a microphone button.
9. WHERE the spoken language is Hindi, THE JAAKBOT farmer-side mode SHALL mark the captured speech "needs human review".
10. IF the browser does not support speech recognition, THEN THE JAAKBOT farmer-side mode SHALL offer the keypad and simulate-speech chips and SHALL continue the flow.

### Requirement 12: JAAKBOT operator-side voice (fixed command grammar)

**User Story:** As an operator, I want a fixed voice command grammar in the console with no LLM and keyboard parity, so that I can drive the demo hands-free safely.

#### Acceptance Criteria

1. THE JAAKBOT operator-side mode SHALL provide a microphone control in the Operator_Console top bar and SHALL recognise only a fixed command grammar: advance one day, jump to next due survey, open follow-up queue, show Hindi, show evidence, start demo, and reset.
2. THE JAAKBOT operator-side mode SHALL NOT use an LLM to interpret commands.
3. WHEN a command is recognised, THE JAAKBOT operator-side mode SHALL display the recognised command as a toast.
4. IF a recognised command is destructive, THEN THE JAAKBOT operator-side mode SHALL require operator confirmation before executing the command.
5. WHEN the operator invokes "Read this aloud", THE JAAKBOT operator-side mode SHALL narrate the open drawer or the Evidence summary using only on-screen data.
6. THE UI SHALL make every JAAKBOT operator-side action reachable by mouse and keyboard.

### Requirement 13: Evidence tab

**User Story:** As a judge, I want an Evidence tab that shows real golden scores, the improvement iterations, schema-validation badges, and a live traceability panel, so that I can verify the agent's quality honestly.

#### Acceptance Criteria

1. THE Evidence tab SHALL display golden results from the Reports files, including the real scores and status_counts and the v0→v4 improvement iteration.
2. WHERE a 2x2 confusion matrix is computable from a report's `cases` array, THE Evidence tab SHALL derive and display it; otherwise THE Evidence tab SHALL display the real scores and SHALL mark the matrix "not shown here".
3. THE Evidence tab SHALL display Hindi validity as the count of schema-valid hi-IN surveys actually present in the data.
4. THE Evidence tab SHALL display latency and token telemetry from the Reports `speed` section and SHALL display cost as "not evidenced" because `cost_usd` is null.
5. THE Evidence tab SHALL display six schema-validation badges, one per Participant_Pack JSON Schema.
6. THE Evidence tab SHALL render the Requirements Traceability panel live, with a deep link for each row.
7. THE Evidence tab SHALL display an "open questions for Digital Green" panel sourced from this spec's Open Questions, and SHALL note that `CONTRACT_QUESTIONS.md` is absent from this repository.
8. THE Evidence tab SHALL display the fixed honesty footer: "Self-reported, simulated answers. Not causal evidence. RCTs remain the verifier."

### Requirement 14: Guided demo mode

**User Story:** As a presenter, I want a pausable four-minute guided walkthrough with a fast "money moment", so that the demo is reliable on both fixtures and the live offline API.

#### Acceptance Criteria

1. THE UI SHALL provide a guided demo mode of approximately four minutes with narration captions that can be paused.
2. WHILE demo mode is active, THE UI SHALL advance to the next step when the operator presses Space and SHALL exit demo mode when the operator presses Escape.
3. THE UI SHALL provide a one-click reset that returns the demo to its initial state.
4. THE Money_Moment SHALL complete within 20 seconds and SHALL perform, in order: step the Simulated_Clock, light the target row, show the push, accept the tap, raise the Hindi Bottom_Sheet, accept a negative answer by tap or by voice, show the green celebration, and show the resulting Follow_Up_Case with its reason chip.
5. THE Money_Moment SHALL complete successfully when the active DataSource is Fixture_Source and when it is Live_Api_Source against the offline Backend_API.

### Requirement 15: Visual language and accessibility

**User Story:** As any user, I want the UI to honour the green design tokens and be fully accessible, so that it is credible on a projector and usable by everyone.

#### Acceptance Criteria

1. THE UI SHALL use only the design-tokens CSS variables for colour and SHALL NOT hard-code hex values in components.
2. WHEN a survey completes, THE UI SHALL display a green-and-white celebration over the backend `thank_you` or `closing_if_follow_up` text.
3. WHILE `prefers-reduced-motion` is set, THE UI SHALL display a static green check instead of confetti and SHALL minimise transitions.
4. THE UI SHALL be fully operable by keyboard and SHALL display a visible focus indicator on every interactive element.
5. THE UI SHALL expose the Bottom_Sheet as an ARIA dialog.
6. THE UI SHALL announce Simulated_Clock changes and JAAKBOT captions through ARIA live regions.
7. THE UI SHALL render all Backend_API strings as text nodes and SHALL NOT display farmer names or raw PII beyond the fields the engine returns.

### Requirement 16: Engineering and testing honesty

**User Story:** As a maintainer, I want strict typing, no unsafe DOM, and thorough tests on both data paths, so that the demo is trustworthy and reproducible.

#### Acceptance Criteria

1. THE UI SHALL be written in strict TypeScript and SHALL NOT use `innerHTML` or `dangerouslySetInnerHTML`.
2. THE UI repository SHALL contain no committed secrets and SHALL provide a `.env.example` declaring `VITE_API_BASE`.
3. THE UI SHALL provide Vitest unit tests covering the three DataSources, fixture schema validation, Bottom_Sheet step logic, clock-and-diff logic, status-chip mapping, the JAAKBOT state machine, and an intent matcher exercised over every `speech` synonym in all six scenarios in both languages.
4. THE UI SHALL provide Playwright end-to-end tests that run against Fixture_Source and against the live offline Backend_API, covering the Money_Moment by tap and by simulated speech, Hindi rendering, channel switching, the API-down fallback banner, the follow-up after a negative answer, and the operator command grammar.
5. THE Playwright end-to-end tests SHALL assert that no console errors occur during the covered flows.
6. THE UI SHALL provide screenshots captured at DSF2 for comparison against the reference image, and THE UI SHALL resolve all serious axe accessibility findings.

## Requirements Traceability

Evidence status is set honestly against THIS repository. "Evidenced" = backed by a verified endpoint, the pack, or a `reports/` file. "Partly" = partly backed; the rest is simulated-in-UI and labelled. "Not shown here" = the brief references it but this repo does not contain it.

| Item | Category | How the UI demonstrates or honestly reports it | Evidence status | Deep link target |
|------|----------|------------------------------------------------|-----------------|------------------|
| Insight ingestion | Must | Pipeline Ingest stage: valid vs quarantined counts from the data layer; `insights.jsonl` (6999 rows) via DataSource | Evidenced | #/pipeline/ingest |
| Survey generation | Must | Generate stage calls `POST /v1/surveys` for one insight; drawer shows returned survey | Evidenced | #/pipeline/generate |
| Survey JSON contract | Must | Six schema-validation badges; fixtures validated against `json/schemas/*.json` | Evidenced | #/evidence/schemas |
| Self-evaluation | Must | Drawer shows validation + self-eval report derived from the `POST /v1/surveys` result | Evidenced | #/drawer/self-eval |
| Evaluation harness (golden) | Must | Evidence tab renders `reports/v0..v4` scores + status_counts (150 cases) | Evidenced | #/evidence/golden |
| Scheduler | Must | Drawer send-window mini-timeline vs crop calendar + 31 Mar; channel order + priority + cap + expiry from `schedule_handoff` + `rules.json` | Evidenced | #/drawer/schedule |
| Broadcaster + simulated app | Should | Phone_Simulator renders per `render/{lang}/{channel}.json`; batch broadcast over HTTP has no endpoint → batch counts labelled simulated-in-UI | Partly | #/phone |
| Hindi | Should | hi-IN surveys/renders verbatim from backend; Evidence counts schema-valid hi-IN surveys; v4 report is hi | Evidenced | #/evidence/hindi |
| Telemetry | Should | Evidence tab shows latency + tokens from `reports.speed`; cost shown as "not evidenced" (`cost_usd` null) | Partly | #/evidence/telemetry |
| Response write-back | Exploratory | Tap persists via `POST /v1/surveys/{flow_id}/responses` when a flow exists; else "simulated tap, not persisted" | Partly | #/phone/responses |
| Negative-outcome follow-up | Exploratory | Negative answer creates a Follow_Up_Case; follow-up queue from `GET /v1/follow-ups` | Evidenced | #/queues/follow-ups |
| Alternative channels | Exploratory | App/Web/WhatsApp/Telegram/Voice render from pack render artifacts and outcome fixtures | Evidenced | #/phone/channels |
| Simulated clock / broadcast diffs / stats / budget / queues | Out-of-scope (no endpoint) | Clock, diff card, human queue labelled "simulated in UI, no backend endpoint" | Partly | #/clock |
| Confusion matrix (TP93/FP0/TN55/FN2) | Out-of-scope (not in repo) | Derived 2x2 only if computable from `cases`; otherwise matrix marked "not shown here"; real scores shown | Not shown here | #/evidence/golden |
| 183 outcome records / cost-per-survey / mismatch ids | Out-of-scope (not in repo) | Outcomes panel uses the 15 real fixture records; cost = "not evidenced"; mismatch ids absent | Not shown here | #/evidence/outcomes |
| Out-of-scope claims (real delivery, production integration, live weather, regions/languages beyond Bihar + en/hi, replacing RCTs) | Out-of-scope (never claim) | Synthetic_Badge persistent; Evidence honesty footer; never ticked | Not shown here | #/evidence |
| DoD: six Must Haves working | DoD | Ingest, Generate, contract, self-eval, harness, scheduler all demonstrable above | Evidenced | #/evidence/dod |
| DoD: full-dataset run | DoD | `insights.jsonl` (6999) surfaced via DataSource; batch run over HTTP labelled simulated-in-UI | Partly | #/pipeline |
| DoD: golden scores + ≥1 improvement iteration | DoD | v0→v4 iterations shown with per-metric scores | Evidenced | #/evidence/golden |
| DoD: retained run versions/outputs/scoring | DoD | `reports/v0..v4` + `history.jsonl` retained and displayed | Evidenced | #/evidence/reports |
| DoD: per-survey + batch timing | DoD | `reports.speed` seconds_per_survey_avg/p95 shown; batch wall seconds shown | Evidenced | #/evidence/telemetry |
| DoD: invalid/low-scoring surveys NOT scheduled | DoD | status_counts (writer_skipped / no_survey / rejected); gate_ok; scenario 6 = no survey | Evidenced | #/evidence/gate |
| DoD: survey JSON validates vs six schemas | DoD | Six schema-validation badges; fixture validation test | Evidenced | #/evidence/schemas |
| DoD: open-source repo | DoD | Repository + README swap instructions + `.env.example` | Evidenced | #/evidence/repo |

## Assumptions

1. **Data-layer-stub decision**: The UI uses the DataSource abstraction with Pack_Source and Fixture_Source so the demo runs offline; Live_Api_Source is a drop-in against the five verified endpoints. No UI code changes are needed to swap in the real dataset.
2. **JAAKBOT-fresh-TS decision**: JAAKBOT in this UI is a new browser-only TypeScript implementation. The existing `jaak_voice` (Python) and `mel_agent/jaak` are not reused by the front end.
3. **Reports-as-golden decision**: Golden/evaluation evidence is sourced from `reports/v0..v4`. `docs/reports/golden_evaluation.json` and the brief's confusion-matrix numbers are absent from this repo and are shown as "not shown here".
4. **CORS-dev allowed**: Adding CORS for the dev origin on the Backend_API is permitted and config-gated; no other backend behaviour changes.
5. **Token-in-memory**: Any operator token is entered at runtime and held in memory only, never persisted.
6. **R0–R8 labels**: `rules.json` expresses eligibility by resolution type and named window/priority/channel/cap rules rather than literal R0–R8 identifiers. The UI will map these to display labels R0–R8 as a presentation convention and surface the underlying rule text from `rules.json`; no rule logic is invented.
7. **Season end**: `rules.json` records `season_end` as `2027-03-31`; the demo narrative's "31 March" refers to this value and the UI uses the rules file as the source of truth.

## Open Questions

1. Does a batch/broadcast endpoint or a clock endpoint need to be added to `mel_agent` later, or does batch activity remain simulated-in-UI for the demo?
2. Will the user's real dataset include human-queue and quarantine states, so those panels can move from "simulated in UI" to Evidenced?
3. Who owns Hindi native-speaker review of the UI-chrome dictionary strings?
4. What is the authoritative source for the exact golden confusion-matrix numbers, given they are absent from this repo?
5. Should taps be persisted when no FarmerChat flow exists, or is the "simulated tap, not persisted" behaviour the intended final behaviour?
