# Implementation Plan: farmerchat-ui

## Overview

This plan converts the approved `design.md` into incremental coding tasks for the
`farmerchat-ui` React + TypeScript + Vite front end under `/frontend`. Each task
builds on prior work and ends by wiring new code into the running app; there is
no orphaned code. Work is ordered in the brief's seven phases, each ending in a
checkpoint. Tasks reference requirement numbers (`R#.n`) and, for property tests,
the design `Property N` numbers.

> **Backend edit policy.** The `mel_agent` behaviour is frozen. The ONLY permitted
> backend edit is the config-gated, additive CORS / optional static-serving task
> (Task 9.4). It is OFF by default (env-gated), adds no endpoints, changes no auth
> and no response shapes. It is marked OPTIONAL and must never be required by any
> front-end task.

**Optional-task convention.** Sub-tasks marked with `*` are optional and MUST NOT
block required tasks. All `fast-check` property tests, the full Playwright e2e
suite, the screenshot/axe sweep, the `CloudVoiceProvider` placeholder, the
live-offline e2e duplicate, and the backend CORS/static task are optional. Core
unit tests (data sources, fixture schema validation, sheet-step, intent matcher,
state-machine basics, clock/diff basics, status-chip map) and the money-moment e2e
on fixtures are NOT optional.

---

## Tasks

- [x] 1. Phase 0 — Scaffold `/frontend`
  - [x] 1.1 Initialise Vite + React 18 + strict TypeScript project
    - Create `frontend/package.json`, `frontend/tsconfig.json` (strict: true), `frontend/vite.config.ts`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/app/App.tsx` (empty shell)
    - Add scripts: `dev`, `build`, `test`, `e2e`, `fixtures`
    - _Requirements: 16.1_
    - _Verify: `npm run build` (cwd frontend) succeeds_
  - [x] 1.2 Add runtime dependencies and self-hosted fonts
    - Install `@tanstack/react-query`, `zustand`, `framer-motion`, `lucide-react`, `@tanstack/react-virtual`
    - Self-host Poppins and Noto Sans Devanagari under `frontend/public/fonts/` and declare `@font-face` in `frontend/src/ui/fonts.css` (no Google CDN)
    - _Requirements: 9.6, 15.1_
    - _Verify: `npm run build` succeeds; grep shows no `fonts.googleapis.com`_
  - [x] 1.3 Configure ESLint, Prettier, and secret hygiene
    - Create `frontend/.eslintrc.cjs`, `frontend/.prettierrc`, `frontend/.env.example` declaring only `VITE_API_BASE`, `frontend/.gitignore`
    - Add an ESLint rule/check forbidding `innerHTML` / `dangerouslySetInnerHTML`
    - _Requirements: 16.1, 16.2_
    - _Verify: `npm run lint`; confirm `.env.example` contains `VITE_API_BASE` and no secrets_
  - [x] 1.4 Configure Vitest and Playwright harnesses
    - Create `frontend/vitest.config.ts`, `frontend/tests/setup.ts`, `frontend/playwright.config.ts`, `frontend/e2e/.gitkeep`
    - Wire `test` → vitest run, `e2e` → playwright
    - _Requirements: 16.3, 16.4_
    - _Verify: `npm run test -- --run` executes (0 tests OK); `npx playwright --version`_

- [x] 2. Checkpoint — scaffold builds
  - Ensure all tests pass, ask the user if questions arise.
  - _Verify: `npm run build` and `npm run lint` succeed_

- [x] 3. Phase 1 — Types, fixtures pipeline, schema validation
  - [x] 3.1 Define shared TypeScript types from the pack JSON
    - Create `frontend/src/data/types.ts` with `Insight`, `Survey`, `SurveyItem`, `Option`, `NoSurvey`, `ScheduleHandoff`, `ResponseRecord`, `ResponseItem`, `RenderArtifact`/`BottomSheetRender`/`VoiceRender`, `Report`, `FollowUp`, `OutcomeCode`, `Language`, `Channel`, `InputKind` (field names verbatim from pack)
    - _Requirements: 3.2, 7.3, 9.3, 10.5_
    - _Verify: `npm run build` type-checks `src/data/types.ts`_
  - [x] 3.2 Build the fixtures generation script
    - Create `frontend/scripts/fixtures/build-fixtures.ts` (`npm run fixtures`): copy pack scenarios, outcomes, six schemas, and `reports/v0..v4` into `frontend/public/fixtures/`; run the offline backend (`POST /v1/surveys` for the 6 scenario insights + a seeded slice) and capture live-shaped decision/survey/handoff results
    - _Requirements: 3.1_
    - _Verify: `npm run fixtures` populates `frontend/public/fixtures/`_
  - [x] 3.3 Write the FixtureSource seed for missing states
    - Extend `build-fixtures.ts` to write a seed under `frontend/public/fixtures/seed/` covering deferred-by-cap, expired, `window_truncated_by_season_end`, a critical human-queue item, and a quarantined ingest row
    - _Requirements: 2.1, 4.4, 6.2, 8.2, 5.2_
    - _Verify: `npm run fixtures`; seed files present_
  - [x] 3.4 Validate every generated artifact against the six schemas
    - Create `frontend/tests/fixtures.schema.test.ts` using `ajv` to validate every generated survey, `ResponseRecord`, and `ScheduleHandoff` against the six pack JSON Schemas; fail on any invalid artifact
    - _Requirements: 3.2, 3.3_
    - _Verify: `npm run test -- tests/fixtures.schema.test.ts`_
  - [x] 3.5 Document the drop-in data swap in the README
    - Create/extend `frontend/README.md` with the procedure to replace fixtures or point `VITE_API_BASE` at the live API with no UI code change
    - _Requirements: 3.4_
    - _Verify: README section present_

- [x] 4. Checkpoint — fixtures validate
  - Ensure all tests pass, ask the user if questions arise.
  - _Verify: `npm run test -- tests/fixtures.schema.test.ts` green_

- [x] 5. Phase 2 — Data layer and source tests
  - [x] 5.1 Define the DataSource port and React Query client/keys
    - Create `frontend/src/data/DataSource.ts` (port interface + method signatures taking `AbortSignal`), `frontend/src/data/client.ts` (React Query client, no `refetchInterval`), `frontend/src/data/queryKeys.ts`
    - _Requirements: 2.1, 2.9_
    - _Verify: `npm run build` type-checks `src/data/*`_
  - [x] 5.2 Implement LiveApiSource against the five endpoints
    - Create `frontend/src/data/LiveApiSource.ts`: `GET /health`, `POST /v1/surveys`, `GET /v1/surveys/{id}`, `POST /v1/surveys/{flow_id}/responses`, `GET /v1/follow-ups`; operator token read from `uiStore` and set as `Authorization` in memory only (never localStorage/URL/logs/repo); every call forwards `AbortSignal`
    - _Requirements: 2.2, 2.3, 2.8_
    - _Verify: `npm run build`; unit test in 5.6_
  - [x] 5.3 Implement PackSource and FixtureSource
    - Create `frontend/src/data/PackSource.ts` and `frontend/src/data/FixtureSource.ts` reading `public/fixtures`; read-helpers (scenarios, renders, timeline, stats, clock model, reports, outcomes, human queue) served from pack/fixtures only
    - _Requirements: 2.1_
    - _Verify: `npm run build`; unit test in 5.6_
  - [x] 5.4 Wire source selection, auto-fallback banner, and manual switch
    - Create `frontend/src/state/uiStore.ts` (active source, in-memory token, selection, settings) and `frontend/src/app/Chrome.tsx` `FallbackBanner`; React Query global `onError` sets source to fixture and raises the banner on transport failure; `DataSourceChip` dropdown switches sources and invalidates queries
    - _Requirements: 2.4, 2.5_
    - _Verify: `npm run build`; e2e in 9.x covers banner_
  - [x] 5.5 Implement loading/empty/error states, pagination, and cancellation
    - Create `frontend/src/data/usePaged.ts` and shared `frontend/src/ui/States.tsx` (loading skeleton, empty state, error + retry); enforce 200-record page cap in `listTimeline`; rely on React Query `AbortSignal` to cancel superseded same-key requests
    - _Requirements: 2.6, 2.7, 2.8_
    - _Verify: `npm run build`; unit test in 5.6_
  - [x] 5.6 Write unit tests for all three DataSources
    - Create `frontend/tests/dataSource.test.ts`: LiveApiSource (fetch mocked, token-in-memory, abort), PackSource, FixtureSource read paths; pagination 200-cap; error→retry state
    - _Requirements: 2.2, 2.3, 2.6, 2.7, 2.8_
    - _Verify: `npm run test -- tests/dataSource.test.ts`_

- [x] 6. Checkpoint — data layer green
  - Ensure all tests pass, ask the user if questions arise.
  - _Verify: `npm run test -- tests/dataSource.test.ts tests/fixtures.schema.test.ts`_

- [x] 7. Phase 3 — Design tokens, shell chrome, phone bottom sheet
  - [x] 7.1 Author tokens.css and the backdrop/device primitives
    - Create `frontend/src/ui/tokens.css` (the ONLY place hex literals live), `frontend/src/ui/Backdrop.tsx`, `frontend/src/ui/DeviceFrame.tsx`
    - _Requirements: 15.1, 9.1_
    - _Verify: `npm run build`; grep shows no hex literals in `.tsx` components_
  - [x] 7.2 Build the split/stacked app shell and honesty chrome
    - Create `frontend/src/app/App.tsx` (HashRouter, split ≥1100 / tabs <1100), `frontend/src/app/routes.ts`, and `Chrome.tsx` additions: persistent non-dismissable `SyntheticBadge` ("SYNTHETIC DATA · SIMULATED DELIVERY"), `DataSourceChip`, `ProvenanceChip`, Hindi/English toggle
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_
    - _Verify: `npm run build`; unit test in 7.6 asserts badge presence and no dismiss control_
  - [x] 7.3 Build reusable token-driven UI primitives
    - Create `frontend/src/ui/SegmentedProgress.tsx`, `OptionRow.tsx`, `PrimaryButton.tsx`, `Chip.tsx`, `Dialog.tsx` (ARIA dialog + focus trap/restore), `LiveRegion.tsx`
    - _Requirements: 6.5, 15.4, 15.5, 15.6_
    - _Verify: `npm run build`; unit test in 7.6_
  - [x] 7.4 Build Confetti with reduced-motion fallback
    - Create `frontend/src/ui/Confetti.tsx` using Framer Motion; render a static green check when `prefers-reduced-motion` is set
    - _Requirements: 15.2, 15.3_
    - _Verify: `npm run build`; unit test in 7.6 asserts static check under reduced motion_
  - [x] 7.5 Implement the BottomSheet with backend-driven steps
    - Create `frontend/src/phone/BottomSheet.tsx` (ARIA dialog): one question per step, backend `step_label`, skip/close/swipe-down-to-close, backend `thank_you`, `opens_when`/`waits_for` tooltip; Hindi verbatim via Noto Sans Devanagari, no clip at 360px; create pure `frontend/src/state/sheetSteps.ts`
    - _Requirements: 9.4, 9.5, 9.6, 1.7, 15.5_
    - _Verify: `npm run build`; unit test in 7.6_
  - [x] 7.6 Write unit test for sheet step logic
    - Create `frontend/tests/sheetSteps.test.ts`: steps visited once in order, use `step_label`, reach `thank_you` only after the last step or stop early on skip/close
    - **Property 6: Sheet step logic is monotonic and bounded**
    - **Validates: Requirements 9.4, 10.1, 10.2**
    - _Requirements: 9.4_
    - _Verify: `npm run test -- tests/sheetSteps.test.ts`_
  - [ ] 7.7* Write property test for sheet step logic (fast-check)
    - Extend `frontend/tests/sheetSteps.prop.test.ts` with `fast-check` ≥100 runs over arbitrary `BottomSheetRender`
    - **Property 6: Sheet step logic is monotonic and bounded**
    - **Validates: Requirements 9.4, 10.1, 10.2**
    - _Verify: `npm run test -- tests/sheetSteps.prop.test.ts`_

- [x] 8. Checkpoint — phone sheet renders
  - Ensure all tests pass, ask the user if questions arise.
  - _Verify: `npm run test -- tests/sheetSteps.test.ts` and `npm run build`_

- [x] 9. Phase 4 — Channels and JAAKBOT voice path
  - [x] 9.1 Build ChannelSwitcher and chat/push/channel renderers
    - Create `frontend/src/phone/ChannelSwitcher.tsx`, `ChatScreen.tsx`, `PushNotification.tsx`, `FarmerSelector.tsx`, `WhatsAppView.tsx`, `TelegramView.tsx`, `VoiceView.tsx` — each rendering exactly from `render/{lang}/{channel}.json`
    - _Requirements: 9.1, 9.2, 9.3_
    - _Verify: `npm run build`; e2e channel switch in 15.x_
  - [x] 9.2 Define the VoiceProvider port and browser/simulated providers
    - Create `frontend/src/voice/VoiceProvider.ts` (interface), `BrowserVoiceProvider.ts` (Web Speech + speechSynthesis, feature-detected, caption fallback), `SimulatedVoiceProvider.ts` (chip row from render `speech` synonyms, silent-WAV TTS + captions)
    - _Requirements: 11.3, 11.7, 11.10_
    - _Verify: `npm run build`; unit test in 9.6_
  - [x] 9.3 Implement the pure farmer-side voice state machine
    - Create `frontend/src/voice/farmerStateMachine.ts` strictly from `voice.json`: ringing/opening/say/listen with `timeout_seconds`, `repeat_if_no_input` once, two consecutive silences → end call + partial `ResponseRecord` + `voice_no_answer`, confirm by reading back matched label, closing / `closing_if_follow_up`, `keypad_out_of_range`
    - _Requirements: 11.1, 11.2, 11.6_
    - _Verify: `npm run build`; unit tests in 9.6/9.7_
  - [x] 9.4 Implement the deterministic intent matcher and input_kind map
    - Create `frontend/src/voice/intentMatcher.ts` (normalise, match only current item's `speech` synonyms + `keypad` digits, no LLM, no free-generated answers) and `frontend/src/state/inputKind.ts` (channel → input_kind)
    - _Requirements: 11.4, 11.5, 12.2, 10.5_
    - _Verify: `npm run build`; unit tests in 9.6/9.8_
  - [x] 9.5 Wire the mic button into the BottomSheet and VoiceView
    - Add a microphone button in `BottomSheet.tsx` and `VoiceView.tsx` that drives the farmer state machine via the active VoiceProvider; captions + listening indicator through `LiveRegion`; Hindi capture marked "needs human review"
    - _Requirements: 11.8, 11.7, 11.9, 15.6_
    - _Verify: `npm run build`; e2e simulated speech in 15.x_
  - [x] 9.6 Write unit tests for voice provider wiring and state-machine basics
    - Create `frontend/tests/voiceStateMachine.test.ts`: feature-detection fallback to keypad/chips; silent-prompt budget; confirm read-back; `keypad_out_of_range` advances
    - _Requirements: 11.1, 11.2, 11.6, 11.10_
    - _Verify: `npm run test -- tests/voiceStateMachine.test.ts`_
  - [x] 9.7 Write unit test for the intent matcher over all synonyms
    - Create `frontend/tests/intentMatcher.test.ts`: exercise EVERY `speech` synonym in all six scenarios in both en-IN and hi-IN; assert match-current-item-only and no cross-item matches
    - _Requirements: 11.4, 11.5, 12.2_
    - _Verify: `npm run test -- tests/intentMatcher.test.ts`_
  - [ ] 9.8* Write property tests for matcher, state machine, and input_kind (fast-check)
    - Create `frontend/tests/voice.prop.test.ts` with `fast-check` ≥100 runs
    - **Property 4: Intent matcher accepts only the current item's synonyms/digits** — **Validates: Requirements 11.4, 11.5, 12.2**
    - **Property 5: Two silent prompts end the call as partial** — **Validates: Requirements 11.1, 11.2, 11.5**
    - **Property 9: Input_kind matches the channel** — **Validates: Requirements 10.5, 11.3**
    - _Verify: `npm run test -- tests/voice.prop.test.ts`_
  - [ ] 9.9* Add the CloudVoiceProvider placeholder (off by default)
    - Create `frontend/src/voice/CloudVoiceProvider.ts`, disabled by default, with a persistent "audio leaves the browser" indicator when enabled
    - _Requirements: 11.3_
    - _Verify: `npm run build`; provider absent from default wiring_

- [x] 10. Checkpoint — voice path works
  - Ensure all tests pass, ask the user if questions arise.
  - _Verify: `npm run test -- tests/voiceStateMachine.test.ts tests/intentMatcher.test.ts`_

- [x] 11. Phase 5 — Console: clock, pipeline, timeline, drawer
  - [x] 11.1 Implement the pure clock/diff engine and clock store
    - Create `frontend/src/state/clockDiff.ts` (`advance(model, state, until)` → delivered/deferredByCap/expired, `blockedUnsafe` always 0) and `frontend/src/state/clockStore.ts` (nowIso, model, step +1h/+1d/+1w, jumpToNextDue)
    - _Requirements: 4.3, 4.4, 4.5_
    - _Verify: `npm run build`; unit test in 11.7_
  - [x] 11.2 Build the ClockPanel with scrubber and diff card
    - Create `frontend/src/console/ClockPanel.tsx`: IST clock labelled "simulated in UI, no backend endpoint", Nov–Mar season scrubber, step buttons, next-due jump, diff card (delivered/deferred/expired, unsafe=0) announced via `LiveRegion`
    - _Requirements: 4.1, 4.2, 4.6, 15.6_
    - _Verify: `npm run build`_
  - [x] 11.3 Implement rulesExplain and the PipelineStrip
    - Create `frontend/src/state/rulesExplain.ts` (map `rules.json` resolution types to plain language + R0–R8 display labels, surface rule text verbatim) and `frontend/src/console/PipelineStrip.tsx` (Ingest→Decide→Generate→Schedule→Deliver→Answer, per-stage counts, valid vs quarantined, Generate calls `POST /v1/surveys`, disable-while-running idempotent, simulated-count labels)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
    - _Verify: `npm run build`; unit test in 11.9_
  - [x] 11.4 Implement statusChips and the virtualized SurveyTimeline
    - Create `frontend/src/state/statusChips.ts` (status → {icon,label}, total, never colour alone) and `frontend/src/console/SurveyTimeline.tsx` (`@tanstack/react-virtual` rows, state chips incl. held-back reasons, filters by crop/topic/language/channel/severity/state)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
    - _Verify: `npm run build`; unit test in 11.8_
  - [x] 11.5 Build the SurveyDrawer full trace
    - Create `frontend/src/console/SurveyDrawer.tsx`: source insight, decision + no_survey codes, items/options/follow_ups, validation + self-eval, send-window mini-timeline vs crop calendar + 31 Mar, channel order + rationale + priority + cap + expiry, provenance + delivery attempts, response answers/status/failure_code/retry/needs_follow_up, bidirectional insight↔survey link
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9_
    - _Verify: `npm run build`_
  - [x] 11.6 Add TopBar chips, token field, and console↔phone connector
    - Create `frontend/src/console/TopBar.tsx` (chips, in-memory token field, mic placeholder) and a connector-pulse element linking console selection to the phone
    - _Requirements: 1.2, 1.3, 1.4, 2.3_
    - _Verify: `npm run build`_
  - [x] 11.7 Write unit test for clock/diff basics
    - Create `frontend/tests/clockDiff.test.ts`: delivered/deferred/expired classification, season-end expiry, `blockedUnsafe === 0`
    - _Requirements: 4.3, 4.4, 4.5_
    - _Verify: `npm run test -- tests/clockDiff.test.ts`_
  - [x] 11.8 Write unit test for the status-chip mapping
    - Create `frontend/tests/statusChips.test.ts`: every status returns exactly one {icon,label}, never undefined, never colour alone
    - _Requirements: 6.2, 6.5_
    - _Verify: `npm run test -- tests/statusChips.test.ts`_
  - [x] 11.9 Write unit test for rulesExplain label mapping
    - Create `frontend/tests/rulesExplain.test.ts`: resolution types map to the expected plain-language text and R0–R8 labels; rule text surfaced verbatim
    - _Requirements: 5.3_
    - _Verify: `npm run test -- tests/rulesExplain.test.ts`_
  - [ ] 11.10* Write property tests for the clock/diff engine (fast-check)
    - Create `frontend/tests/clockDiff.prop.test.ts` with `fast-check` ≥100 runs
    - **Property 1: Clock diff partitions affected surveys** — **Validates: Requirements 4.3, 4.4, 4.5**
    - **Property 2: Expiry respects season end and expires_at** — **Validates: Requirements 4.3, 4.4**
    - **Property 3: Frequency cap defers within window** — **Validates: Requirements 4.3, 4.4**
    - _Verify: `npm run test -- tests/clockDiff.prop.test.ts`_
  - [ ] 11.11* Write property test for status-chip totality (fast-check)
    - Create `frontend/tests/statusChips.prop.test.ts` with `fast-check` ≥100 runs
    - **Property 7: Status-chip mapping is total and icon+label** — **Validates: Requirements 6.2, 6.5**
    - _Verify: `npm run test -- tests/statusChips.prop.test.ts`_

- [x] 12. Checkpoint — console wired
  - Ensure all tests pass, ask the user if questions arise.
  - _Verify: `npm run test -- tests/clockDiff.test.ts tests/statusChips.test.ts tests/rulesExplain.test.ts`_

- [x] 13. Phase 6 — Queues, Evidence, demo mode, operator voice
  - [x] 13.1 Build the follow-up and human queues
    - Create `frontend/src/console/Queues.tsx`: `FollowUpQueue` from `GET /v1/follow-ups` with reason chips; `HumanQueue` of critical insights from fixtures/pack labelled "simulated in UI, no backend endpoint" with local status change ("simulated reviewer view"); fixed-template acknowledgement only, never agronomic/veterinary/health advice
    - _Requirements: 8.1, 8.2, 8.3, 8.4_
    - _Verify: `npm run build`_
  - [x] 13.2 Implement negative-answer follow-up write-back and tap handling
    - Wire `BottomSheet`/`VoiceView` so a tap with a flow persists via `POST /v1/surveys/{flow_id}/responses`; no flow → local simulation labelled "simulated tap, not persisted"; a negative answer creates a `Follow_Up_Case` without further operator action; add `frontend/src/phone/SimulateBehaviour.tsx` replaying the outcome_codes grid with retry_decision/retry_after_minutes/counts_toward_cap
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_
    - _Verify: `npm run build`; unit test in 13.8_
  - [x] 13.3 Build the Evidence tab panels
    - Create `frontend/src/console/EvidenceTab.tsx` and `frontend/src/evidence/reports.ts`: golden scores grid + v0→v4 improvement SVG + status_counts; Hindi validity count; telemetry from `reports.speed` with cost = "not evidenced"; six schema-validation badges; honesty footer verbatim
    - _Requirements: 13.1, 13.3, 13.4, 13.5, 13.8_
    - _Verify: `npm run build`_
  - [x] 13.4 Implement the computable-only confusion matrix
    - Create `frontend/src/evidence/confusionMatrix.ts`: derive the 2×2 from each case's `expected_survey`/`agent_survey` only if computable; otherwise return null and render "not shown here"
    - _Requirements: 13.2_
    - _Verify: `npm run build`; unit test in 13.9_
  - [x] 13.5 Build the live Requirements Traceability panel
    - Create `frontend/src/console/RequirementsPanel.tsx` bound to the traceability table with a deep link per row; add the "open questions for Digital Green" panel noting `CONTRACT_QUESTIONS.md` is absent
    - _Requirements: 13.6, 13.7_
    - _Verify: `npm run build`_
  - [x] 13.6 Implement the guided demo director and money moment
    - Create `frontend/src/demo/director.ts` and `frontend/src/state/demoStore.ts`: ~4-min pausable narration, Space = next, Escape = exit, one-click reset; money moment sequence (step clock → light row → push → tap/voice negative → Hindi sheet → celebration → follow-up case) targeting <20s
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_
    - _Verify: `npm run build`; unit test in 13.10_
  - [x] 13.7 Implement the operator-side fixed command grammar
    - Create `frontend/src/voice/operatorGrammar.ts` and wire the TopBar mic: fixed commands (advance one day, jump to next due, open follow-up queue, show Hindi, show evidence, start demo, reset), no LLM, recognised-command toast, confirm on destructive reset, "read this aloud" using on-screen data only, full mouse+keyboard parity
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_
    - _Verify: `npm run build`; unit test in 13.11_
  - [x] 13.8 Write unit test for response round-trip and input_kind
    - Create `frontend/tests/responseRoundTrip.test.ts`: voice vs tap `ResponseRecord` identical except per-item `input_kind`; negative answer yields a follow-up case
    - _Requirements: 10.4, 10.5_
    - _Verify: `npm run test -- tests/responseRoundTrip.test.ts`_
  - [x] 13.9 Write unit test for the confusion matrix
    - Create `frontend/tests/confusionMatrix.test.ts`: computable case yields a 2×2; missing booleans yield null → "not shown here"
    - _Requirements: 13.2_
    - _Verify: `npm run test -- tests/confusionMatrix.test.ts`_
  - [x] 13.10 Write unit test for money-moment director logic
    - Create `frontend/tests/director.test.ts`: money-moment steps fire in order; reset returns to initial state; pause/step transitions correct
    - _Requirements: 14.3, 14.4_
    - _Verify: `npm run test -- tests/director.test.ts`_
  - [x] 13.11 Write unit test for operator command grammar
    - Create `frontend/tests/operatorGrammar.test.ts`: only fixed phrases recognised, no LLM, reset requires confirmation, each command maps to its action
    - _Requirements: 12.1, 12.2, 12.4_
    - _Verify: `npm run test -- tests/operatorGrammar.test.ts`_
  - [ ] 13.12* Write property test for voice/tap round-trip (fast-check)
    - Create `frontend/tests/responseRoundTrip.prop.test.ts` with `fast-check` ≥100 runs
    - **Property 8: Voice vs tap responses differ only by input_kind** — **Validates: Requirements 10.5**
    - _Verify: `npm run test -- tests/responseRoundTrip.prop.test.ts`_

- [x] 14. Checkpoint — full console + phone integrated
  - Ensure all tests pass, ask the user if questions arise.
  - _Verify: `npm run test -- --run` and `npm run build`_

- [ ] 15. Phase 7 — Polish, accessibility, e2e, docs
  - [x] 15.1 Write the money-moment e2e on fixtures (required demo path)
    - Create `frontend/e2e/money-moment.spec.ts` running against Fixture_Source: money moment by tap AND by simulated speech; assert no console errors
    - _Requirements: 14.4, 14.5, 16.4, 16.5_
    - _Verify: `npm run e2e -- e2e/money-moment.spec.ts`_
  - [ ] 15.2* Write the remaining Playwright e2e suite
    - Create `frontend/e2e/flows.spec.ts`: Hindi rendering (no clip at 360px), channel switching, API-down fallback banner, follow-up after negative answer, operator command grammar; assert no console errors; also run the money moment against the live offline Backend_API
    - _Requirements: 16.4, 16.5_
    - _Verify: `npm run e2e -- e2e/flows.spec.ts`_
  - [ ] 15.3* Capture DSF2 and 360px screenshots and resolve axe findings
    - Create `frontend/e2e/screenshots.spec.ts` capturing 1440×900 and 360px views (split mid-demo, Hindi sheet each step + confetti, journey intro/question/almost-there/thank-you, JAAKBOT listening+confirming, each channel, drawer, follow-up queue, Evidence+Requirements, stacked narrow) and run axe; resolve all serious findings
    - _Requirements: 15.3, 16.6_
    - _Verify: `npm run e2e -- e2e/screenshots.spec.ts`_
  - [ ] 15.4* Add the config-gated backend CORS / static-serving edit (ONLY permitted backend change)
    - Add env-gated `CORSMiddleware` (e.g. `MEL_CORS_DEV_ORIGIN`) and optional static serving of the built UI in `mel_agent`; OFF when env unset; no new endpoints, no auth change, no response-shape change
    - _Requirements: 2.4 (Assumption 4)_
    - _Verify: with env unset, backend behaviour unchanged; with env set, dev origin allowed_
  - [ ] 15.5 Write the README and DEMO_NOTES
    - Finalise `frontend/README.md` (run live/fixtures/pack, swap-in data, build+serve, demo script, shortcuts, JAAKBOT setup + browser support, known limits) and create `frontend/DEMO_NOTES.md` (4-min talk track, fallback plan, likely judge questions with honest answers)
    - _Requirements: 3.4, 13.7_
    - _Verify: both files present with the required sections_

- [ ] 16. Final checkpoint — demo-ready
  - Ensure the full unit suite is green (`npm run test -- --run`), the money-moment e2e passes on fixtures (`npm run e2e -- e2e/money-moment.spec.ts`), `npm run build` succeeds, the persistent Synthetic_Badge is present, and README + DEMO_NOTES are complete. Ask the user if questions arise.
  - _Requirements: 1.2, 14.4, 16.4_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; they never block required tasks.
- Optional set: all `fast-check` property tests (7.7, 9.8, 11.10, 11.11, 13.12), the full Playwright e2e suite (15.2), the screenshot/axe sweep (15.3), the CloudVoiceProvider placeholder (9.9), and the backend CORS/static task (15.4).
- Required tests: data sources (5.6), fixture schema validation (3.4), sheet step (7.6), intent matcher (9.7), voice state-machine basics (9.6), clock/diff basics (11.7), status-chip map (11.8), rulesExplain (11.9), response round-trip (13.8), confusion matrix (13.9), director (13.10), operator grammar (13.11), and the money-moment e2e on fixtures (15.1).
- Each task references specific requirement clauses; test tasks reference the design Property numbers they validate.
- The backend CORS/static-serving task (15.4) is the ONLY permitted backend edit, is config-gated, additive, and OFF by default.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4"] },
    { "id": 2, "tasks": ["3.1", "3.2"] },
    { "id": 3, "tasks": ["3.3", "3.5"] },
    { "id": 4, "tasks": ["3.4", "5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "5.5"] },
    { "id": 6, "tasks": ["5.6", "7.1"] },
    { "id": 7, "tasks": ["7.2", "7.3", "7.4"] },
    { "id": 8, "tasks": ["7.5", "9.1", "9.2"] },
    { "id": 9, "tasks": ["7.6", "9.3", "9.4"] },
    { "id": 10, "tasks": ["9.5", "9.6", "9.7", "11.1", "11.3", "11.4"] },
    { "id": 11, "tasks": ["11.2", "11.5", "11.6", "11.7", "11.8", "11.9"] },
    { "id": 12, "tasks": ["13.1", "13.3", "13.4", "13.5", "13.6", "13.7"] },
    { "id": 13, "tasks": ["13.2", "13.8", "13.9", "13.10", "13.11"] },
    { "id": 14, "tasks": ["15.1", "15.5"] },
    { "id": 15, "tasks": ["7.7", "9.8", "9.9", "11.10", "11.11", "13.12", "15.2", "15.3", "15.4"] }
  ]
}
```
