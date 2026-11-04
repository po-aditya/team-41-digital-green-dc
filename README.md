# FarmerChat Contextual MEL Survey Agent

Hackathon MVP for Digital Green. Reads FarmerChat insights, decides which ones
deserve a follow-up survey, writes short tap-answer surveys in the farmer's
language, hands them to a scheduler, and simulates delivery and farmer answers.
Runtime LLM inference uses Amazon Bedrock behind a hard spending control; the
whole pipeline also runs fully offline with a deterministic template provider.

**Workspace status:** The phased MVP is the primary application in this
workspace. Kevin's model-based prototype and phone mockup are preserved separately in
`prototypes/kevin/`; Jeremiah's FarmerLoop and response-conformance work are in
`farmerloop/`. All three use the unchanged synthetic pack at `data/participant-pack/`.
They have separate runtimes and stores; their APIs and evaluation scores are not
interchangeable. See [the branch review](docs/BRANCH_REVIEW.md) for the comparison,
source history, document inventory, limitations, and prototype commands.

The uploaded vision and technical Word documents remain in
[`docs/Digital Green Foundation/`](docs/Digital%20Green%20Foundation/).
The [interactive briefing](docs/farmerchat-briefing/index.html) and
[architecture diagram](docs/dynamichtml-diagram.html) are also retained.

Independent application validation results are recorded in
[the validation report](docs/CONSOLIDATION_VALIDATION.md).

## AWS deployment

The [Terraform deployment guide](Terraform/README.md) describes deployment from
another computer into an explicitly selected AWS account. The package provides
an internet-facing Application Load Balancer in `us-east-1` and persistent storage
for the current SQLite sandbox. Initial HTTP access uses the load balancer's AWS
hostname for the synthetic demo; operator APIs remain accessible through Systems
Manager tunnels. It preserves the alternate prototypes as separate runtimes.
Terraform prints the application URL after deployment. Optional authenticated
HTTPS access requires a domain and DNS configuration.

The infrastructure has not been deployed. Read the guide's validation evidence,
target-account checks, secret setup, and sandbox limitations before applying it.

## What it does

```
insights.jsonl ─▶ ingest (validate, quarantine, reconcile CSV; run marked complete/failed)
               ─▶ decide (R0..R8: quarantine / no_survey / survey; critical → human queue)
               ─▶ generate (template or Bedrock) ─▶ self-evaluate (schema, catalogue, characters,
                                                     content policy, language, relevance)
               ─▶ schedule (send window, channel order, cap, priority, expiry) = schedule_handoff
               ─▶ broadcaster stub on a simulated clock (atomic claims, re-checks content before send)
               ─▶ simulated farmer answers = response records ─▶ follow-up queue, evaluation reports
```

All six organisation-provided schemas are enforced unchanged. Every survey,
hand-off, no-survey document, bottom sheet and answer record validates against them.

## Layout

```
src/mel_agent/
  main.py                FastAPI app: /healthz (public); all other routes need the operator token
  cli.py / __main__.py   python -m mel_agent ingest|decide|generate|broadcast|evaluate|run-all|demo|budget
  config.py              Settings from MEL_* env vars (paid inference OFF by default)
  contracts/             the six schemas, Draft 2020-12, local $ref, format checks
  data/                  pack paths, rules.json / outcome_codes.json views, ingestion + quarantine
  store/                 SQLite (portable SQL): insights, decisions, generation claims, surveys,
                         hand-offs, attempts, responses, audit log, budget ledger
  rules/                 eligibility (R0..R8), send-window timing, hand-off builder
  generation/            provider protocol, closed answer catalogue, template provider (en-IN, hi-IN),
                         Bedrock provider, content-policy checks, bounded attempts + fallback
  budget/                durable Decimal ledger: reserve → call → settle | unresolved → reconcile
  llm/                   Bedrock client, pricing, BudgetedInvoker (the only route to paid inference)
  delivery/              simulated clock, scheduler/broadcaster, answer simulator, bottom-sheet renderer
  evaluation/            golden-set confusion matrix + timing/format/relevance proxies
  pipeline.py            idempotent orchestration;  demo.py  eight end-to-end cases
config/bedrock_pricing.json   from the AWS Price List API
requirements/                 hashed lockfiles (runtime, dev, build) + tested-py314.txt
docs/IMPLEMENTATION_PLAN.md   requirements audit, derived golden rules, design decisions
docs/CONTRACT_QUESTIONS.md    where the supplied materials disagree and what we chose meanwhile
docs/REVIEW_HANDOFF.md        how to reproduce every check
docs/reports/golden_evaluation.{json,md}   `python -m mel_agent evaluate --out docs/reports`
tests/                        incl. tests/test_regressions_codex.py (one section per review finding)
```

The participant pack is read in place from `data/participant-pack/` (override with
`MEL_PARTICIPANT_PACK_DIR`). The supplied schemas and data are preserved unchanged.
Docker Compose mounts this directory read-only and binds the API to localhost.

## Setup

Supported: Python 3.12+. Tested on CPython 3.14.4 and CPython 3.12.16 (the Docker base).

```bash
python3 -m venv .venv            # if ensurepip is missing: python3 -m venv --without-pip .venv
                                 # then: curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
.venv/bin/pip install --require-hashes -r requirements/dev.lock
.venv/bin/pip install --no-deps -e .
cp .env.example .env             # set MEL_OPERATOR_TOKEN (API) and MEL_BEDROCK_REGION (Bedrock)
```

No dependencies were added after Phase 0; the lockfiles are unchanged.

## Run it offline (no AWS needed)

```bash
.venv/bin/python -m mel_agent demo --out var/demo          # 8 end-to-end cases, ~2 s
.venv/bin/python -m mel_agent evaluate --out var/reports   # golden-set evaluation
.venv/bin/python -m mel_agent run-all --until 2027-04-05T00:00:00+05:30 --step-minutes 180
                                                           # whole dataset + whole simulated season
MEL_OPERATOR_TOKEN=<16+ chars> .venv/bin/uvicorn mel_agent.main:app --port 8000   # http://127.0.0.1:8000/docs
```

Typical API session (every call except `/healthz` carries the operator header):

```bash
H='X-Operator-Token: <the same token>'
curl -X POST -H "$H" localhost:8000/runs/ingest
curl -X POST -H "$H" localhost:8000/runs/decide
curl -X POST -H "$H" localhost:8000/runs/generate -H 'content-type: application/json' -d '{"limit": 50}'
curl -X POST -H "$H" localhost:8000/runs/broadcast -H 'content-type: application/json' -d '{"until": "2026-12-31T19:00:00+05:30"}'
curl -H "$H" 'localhost:8000/surveys?limit=5' ; curl -H "$H" 'localhost:8000/surveys/S-000138?render=bottom_sheet'
curl -H "$H" 'localhost:8000/responses?needs_follow_up=true' ; curl -H "$H" localhost:8000/human-queue ; curl -H "$H" localhost:8000/stats
```

### Operator access

- One shared secret, `MEL_OPERATOR_TOKEN` (at least 16 characters), sent as
  `X-Operator-Token`; compared in constant time. Required by every route except
  `/healthz` and the OpenAPI documents: workflow triggers, paid inference and
  all record-level reads. Unset → those routes answer **503** (fail closed).
- Validation errors return field locations and messages only, never the
  submitted values. Unhandled errors return a generic 500 without a traceback.
- **Production limitation:** a single shared credential with no identity,
  roles, rotation or per-caller audit. Adequate for a sandbox behind a trusted
  network; a public deployment needs an identity provider and per-operator roles.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` (public) | liveness; schemas loaded; provider and paid-inference flags |
| GET | `/insights`, `/insights/{id}`, `/quarantine` | ingested records with provenance, filters, pagination (≤200) |
| GET | `/farmers`, `/farmers/{id}` | farmer registry |
| GET | `/decisions`, `/decisions/{insight_id}`, `/human-queue` | eligibility decisions, external `no_survey` document, critical cases |
| GET | `/surveys`, `/surveys/{id}?render=bottom_sheet&channel=app` | survey document, validation report, bottom sheet |
| GET | `/handoffs`, `/handoffs/{id}` | scheduler hand-offs, delivery state, attempts |
| GET | `/deliveries`, `/responses`, `/responses/{key}`, `/follow-up-queue` | simulated attempts and answer records |
| GET | `/stats`, `/stats/ingestion`, `/audit`, `/budget` | counters, ingestion status, audit log, spend ledger |
| POST | `/runs/ingest`, `/runs/decide`, `/runs/generate`, `/runs/process/{id}`, `/runs/broadcast`, `/runs/evaluate` | workflow triggers; bounded, idempotent, offline by default |
| GET | `/runs/clock` | simulated clock |

`/runs/generate` with `provider=bedrock` needs `confirm_paid: true` **and**
`MEL_ALLOW_PAID_INFERENCE=true` **and** an app started with
`MEL_GENERATION_PROVIDER=bedrock`; otherwise 403/409. Read endpoints never call AWS.

## Data import and database upgrades

- Ingestion is **atomic**: farmers, calendar, insights, CSV reconciliation, golden
  cases and the run record are written in one database transaction. A failure
  anywhere rolls the whole import back, so the previously completed dataset stays
  active and untouched, and the failed run is recorded afterwards. Runs are ordered
  by execution sequence (never by the simulated `now` they were given) and every
  run has a unique id; every insight row records the run that wrote it. Readers
  (API, CLI, broadcaster) see either the previous complete snapshot or the new one,
  never a mixture.
- The database schema is versioned (`schema_version` in the `kv` table, currently
  3). The stored version is read and validated **before** any statement touches the
  database: supported are a fresh file, the unmarked legacy layouts (versions 1 and
  2) and version 3. Any other marker (newer, zero, negative, non-numeric) is refused
  with a `StoreError` that names the version, and the file, including its marker,
  is left untouched; there is no downgrade. Opening a supported older database
  applies a small idempotent migration inside one transaction: it only adds
  columns with defaults (`generation_claims.token/lease_until`,
  `ingest_runs.seq/recorded_at`, `insights.run_id`) and the ledger uniqueness
  indexes. Existing rows are preserved; legacy in-progress claims come back with
  an expired lease and are taken over normally. An interrupted upgrade leaves the
  old version intact and the next start completes it; concurrent starters
  serialise. If the ledger already holds duplicate reservation events the upgrade
  refuses with a clear error and nothing is changed. Downgrading is not supported.

## Rules, timing and the golden set

- Eligibility applies `rules.json` plus a content signature for junk; the
  precedence table is in `docs/IMPLEMENTATION_PLAN.md`. `quality_flag` is never
  read by the decision code (a test enforces this). A `critical` record is routed
  to the human queue before any junk test, even when its other fields look like
  small talk.
- Send windows follow `rules.json` exactly and reproduce the five worked scenarios.
- **Held-back windows (provisional policy):** `rules.json` requires both a window
  at least two days wide and nothing after 31 March. For 36 insights created
  16–29 March both cannot hold; they are held back as
  `window_truncated_by_season_end` instead of being sent with a shortened window.
  This is an unresolved contract question (see `docs/CONTRACT_QUESTIONS.md` §2),
  not a tuning choice, and it costs one golden case (I-006836).
- `no_survey.schema.json` permits only two reason codes; richer internal reasons
  are kept separately and mapped. Critical cases also land in `/human-queue`.
- Golden evaluation (150 cases, en-IN templates): **TP 93, FP 0, TN 55, FN 2**
  (precision 1.0, recall 0.979, accuracy 0.987), no-survey reason codes 55/55,
  first channel 93/93. The two misses are the two documented contract
  disagreements (`docs/CONTRACT_QUESTIONS.md` §2 and §3). The previous 149/150
  figure came from sending windows the rules forbid; this is not an accuracy
  regression but a policy choice awaiting Digital Green.

## Survey generation and content policy

- `template` provider (default): deterministic, free, en-IN and hi-IN.
  **Hindi text has not been reviewed by a Hindi speaker.**
- `bedrock` provider: structured prompt, insight passed as a compact JSON data
  block (never as instructions), strict single-document JSON parsing (duplicate
  keys and NaN rejected), bounded attempts, fallback to the template provider.
  Attempts whose output is unusable are still accounted for. **No real-model
  output has been generated or evaluated.**
- **Answer sets are fixed per question intent.** Every intent declares the outcomes
  it must always offer (for the current catalogue: its whole answer set, e.g.
  *better / same / worse*, or *easily / with difficulty / could not get it*), so a
  model cannot narrow the answers into only-positive choices or drop the option
  that carries a follow-up signal. Coverage is validated when a survey is assembled,
  when it is checked and again before every send (`required_outcome_missing`,
  `follow_up_signal_missing`).
- **Questions and answer options come from a closed catalogue**
  (`generation/catalog.py`). A survey is a list of *question intents*; each intent
  has a vetted en-IN/hi-IN template whose only variable parts are glossary slots
  filled from the insight's structured fields (asset name or category, concern
  category, expert type). A model may choose *which* intents to ask (from those
  allowed for the insight's resolution type) and nothing else: it cannot write
  wording or change an answer set, and farmer-visible labels are always catalogue
  text. Free text from a model or from the insight never reaches a farmer. Before
  scheduling and again before every send, each question is checked to be an exact
  catalogue rendering (`prompt_not_from_catalogue`) and each item is checked
  against the intent's approved definition: type, the complete fixed answer set
  with its follow-up reasons, and for scale questions the exact minimum, maximum,
  follow-up threshold and follow-up reason (`scale_definition_mismatch`,
  `follow_up_signal_missing`). A schema-valid stored document is never assumed to
  be semantically safe.
- Model-written wording is refused by default (`freeform_question_not_allowed`).
  With `MEL_GENERATION_ALLOW_FREEFORM=true` such surveys are stored as
  `pending_approval` for a human decision and are never scheduled or sent by the
  pipeline; no approval UI exists yet (the status is visible through `/surveys`).
- Every visible field (stems, labels) and the rationale also passes a lexical content policy:
  Unicode allow-list (Latin + Devanagari; control, bidi and zero-width characters
  and homoglyph scripts rejected), no URLs/handles/phone numbers, no personal-data
  requests, no advice or imperatives, no dose-like quantities, no hazardous
  substances, stems must be questions, right language. Failing surveys are stored
  as `rejected` and never reach a hand-off; the broadcaster re-runs the policy
  before every send (`blocked_unsafe`).

## Scheduling and delivery (simulated)

- Hand-off = survey + window + `send_hours` 07:00–19:00 + channel order
  (preferred → method channel → WhatsApp → voice for high priority) + weekly cap
  (1 per farmer per 7 days, high priority exempt) + expiry (window end + 2 days).
- The send decision is one database transaction: re-read state, count the cap
  (including in-flight sends), claim the attempt row. Two workers — threads or
  processes — cannot both send for one hand-off or both pass a farmer's cap.
- Successor state (`retry_scheduled` / `fallback_scheduled`) is written in the
  same transaction as the attempt's outcome, so a crash between "attempt over"
  and "next attempt sent" is recovered by the next tick, in any process.
- Generation is protected by a durable per-insight claim; a survey id belongs to
  exactly one insight; an existing hand-off is never reset by re-generation.
- Farmer reactions come from a seeded simulator (or a scripted one for demos).
  **Nothing is ever sent to a real channel; exactly-once delivery to a real
  provider is not claimed and would need the provider's idempotency key.**

## AWS region and credentials

**No AWS region is assumed.** Set it explicitly when using Bedrock:

```bash
export MEL_BEDROCK_REGION=us-west-2   # or AWS_REGION / AWS_DEFAULT_REGION
```

Lookup order: `MEL_BEDROCK_REGION`, then `AWS_REGION`, then `AWS_DEFAULT_REGION`.
Credentials come from the standard boto3 chain. Nothing in this repo stores them.

## Spending controls

The dollar amounts are **hackathon configuration** (`MEL_BUDGET_STOP_USD=225`,
`MEL_BUDGET_MAX_USD=250`), separate from eligibility and generation logic.

- `MEL_ALLOW_PAID_INFERENCE` defaults to **false**; no code path (API, CLI, smoke
  script) reaches Bedrock without it.
- Every paid request reserves a conservative estimate (3 chars/token, full
  `max_tokens`, × 1.25) in a durable Decimal ledger before it is sent; refused when
  committed + estimate would exceed the cutoff. The paid client is built with SDK
  transport retries **disabled** (`total_max_attempts=1`) and refuses to run on a
  client configured otherwise, so one reservation is always one request on the
  wire. Retries are explicit application attempts (`MEL_BEDROCK_PAID_APP_ATTEMPTS`,
  default 2), each reserved separately and each preceded by the caller's ownership
  check, so a worker that lost its generation claim never starts another paid
  request. Timeouts keep their estimate committed as *unresolved* and are not
  retried unless `MEL_BEDROCK_PAID_RETRY_AFTER_TIMEOUT=true`.
- **Order of operations** for a paid call: ownership check → authorisation, pricing
  and headroom (`reserve`) → construct the credential-bearing client → ownership
  check again, immediately before submitting (lost ownership releases the unused
  reservation; nothing was sent) → send → settle. A request refused at any gate
  performs no client construction and no credential lookup, and a worker that lost
  its claim during client construction submits nothing.
- **Error classification** (`llm/budgeted.py`): a reservation is *released* only
  when the SDK reports a well-formed `RetryAttempts == 0` **and** the error code
  says the request was rejected before any model work: throttling, too many
  requests, quota exceeded, model not ready (retryable) or validation, access
  denied, resource not found, bad credentials (not retryable). Retry metadata has
  three states: verified zero, verified positive, unknown (missing or malformed
  envelope, field or type). Only verified zero allows the ordinary classification.
  Everything else is *unresolved*: `ModelErrorException`, `ModelTimeoutException`,
  internal or unavailable service errors, unknown codes, any `RetryAttempts > 0`,
  unknown retry metadata on an error or a success, a success without verifiable
  usage, timeouts. Unresolved
  outcomes stop the attempt loop, and while `MEL_BUDGET_MAX_UNRESOLVED` (default 3)
  reservations are unresolved no new paid attempt is reserved until an operator
  reconciles them.
- Settlement uses **verified** usage only. A reply without a usable usage block
  (missing, malformed, or text with zero output tokens) leaves the full estimate
  committed as *unresolved* until a human reconciles it:
  `python -m mel_agent budget status` / `budget reconcile --reservation-id … --actual-usd …`.
- Ledger rows are validated on every read; negative or non-finite amounts, unknown
  kinds, settlements without reservations, double finalisation or a second
  reconciliation make the ledger unavailable and all reservations are refused.
  Storage enforces one row per (reservation, kind) and one terminal row per
  reservation, so a duplicate written by a concurrent operator or a bug is
  rejected at insert time. Settings reject non-finite or unbounded amounts.
- Generation claims are owned by a fencing token with a real-time lease
  (`MEL_GENERATION_LEASE_SECONDS`, default 300); the simulated clock never expires
  one. A worker that outlives its lease cannot persist a survey or hand-off, but
  it may already have performed one paid inference: after a genuine lease expiry
  one duplicate inference per insight is possible and is accounted for normally.
- **Limitations:** this meters only calls made through this application; console
  use, other tools or accounts are invisible to it. AWS billing lags by hours and
  is the source of truth. No application can guarantee an AWS bill.

## Test

```bash
.venv/bin/pytest                  # offline suite; no AWS calls, no cost (~60 s)
MEL_RUN_BEDROCK_SMOKE=1 MEL_ALLOW_PAID_INFERENCE=true .venv/bin/pytest -m bedrock   # one paid call, opt-in
```

An autouse fixture fails any test that attempts a real HTTP call through botocore.
`tests/test_regressions_codex.py` holds one section per finding of the first
independent review, including process-level concurrency and crash-recovery tests.

## Docker

```bash
docker compose up --build
```

The root Compose image and its volume wiring have not been exercised in this
validation. The separate deployment images under `Terraform/images/` have been
built and smoke-tested; see [infrastructure validation](Terraform/VALIDATION.md).
The application suite also passed directly on CPython 3.12.16.

## Known limitations

- The primary runtime renders bottom-sheet JSON through its API/CLI; Kevin's separate prototype supplies the Streamlit demo.
- Hindi templates unreviewed; Bedrock output unevaluated (no paid calls were authorised).
- Content policy is deterministic (closed catalogue plus allow-lists and lexicons for English and Hindi), not a judgement of meaning.
- Eligibility's readability floor is script-neutral but lexical only; fluent nonsense in any script passes it (see `docs/CONTRACT_QUESTIONS.md` §6).
- Free-form (model-written) questions have no approval workflow; when enabled they only accumulate as `pending_approval`.
- Operator access is a single shared token (see above).
- Contract disagreements in `docs/CONTRACT_QUESTIONS.md` await Digital Green.
- PostgreSQL not wired; the SQL is portable but only SQLite is exercised.
