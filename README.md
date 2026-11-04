# FarmerChat Contextual MEL Survey Agent

Hackathon MVP for Digital Green. Reads FarmerChat insights, decides which ones
deserve a follow-up survey, writes short tap-answer surveys, hands them to a
scheduler, and simulates farmer answers. Runtime LLM inference uses Amazon Bedrock.

**Status: Phase 0 (foundation).** Health endpoint, configuration, schema
validation, Bedrock adapter, pricing config. No survey workflow yet.

## Layout

```
source-code/
  src/mel_agent/
    main.py              FastAPI app (GET /healthz)
    config.py            Settings from MEL_* env vars
    contracts/schemas.py Loads the 6 pack schemas, Draft 2020-12, local $ref, format checks
    llm/bedrock.py       boto3 Bedrock client, model discovery, Converse wrapper (usage + latency)
    llm/pricing.py       Pricing table loader/validator, per-call cost estimate, budget thresholds
  config/bedrock_pricing.json   Generated from the AWS Price List API
  requirements/
    runtime.lock         Hashed, pinned runtime deps (all Python >= 3.12); used by Docker
    dev.lock             runtime.lock + test deps
    build.lock           Hashed build backend (setuptools)
    tested-py314.txt     Exact environment the test suite passed on (pip freeze)
  scripts/
    discover_bedrock.py         List models / inference profiles (free)
    fetch_bedrock_pricing.py    Regenerate the pricing file (free, validated, atomic)
    bedrock_smoke.py            One tiny paid call (needs --yes)
    lock_dependencies.sh        Regenerate requirements/*.lock
  tests/
```

The participant pack is read in place from
`../mel-survey-agent-participant-pack/participant-pack` (override with
`MEL_PARTICIPANT_PACK_DIR`). It is never copied or modified.

## Setup

Supported: Python 3.12+. Tested on:

- **CPython 3.14.4, Linux x86_64** (development venv): full suite.
- **CPython 3.12.16, Linux x86_64** (same version as the Docker base image),
  installed from `requirements/dev.lock`: full suite.

Reproducible install (exact, hash-checked versions):

```bash
cd source-code
python3 -m venv .venv            # if ensurepip is missing: python3 -m venv --without-pip .venv
                                 # then: curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
.venv/bin/pip install --require-hashes -r requirements/dev.lock
.venv/bin/pip install --no-deps -e .
cp .env.example .env             # then set MEL_BEDROCK_REGION
```

`pip install -e '.[dev]'` also works but resolves the newest versions allowed by
`pyproject.toml`, which may differ from what was tested.

To regenerate the lockfiles (needs [uv](https://docs.astral.sh/uv/) in a separate
tools environment), run `scripts/lock_dependencies.sh`. It is constrained to
`requirements/tested-py314.txt`, so it does not upgrade anything by itself.

## AWS region and credentials

**No AWS region is assumed.** Set it explicitly:

```bash
export MEL_BEDROCK_REGION=us-west-2   # or AWS_REGION / AWS_DEFAULT_REGION
```

Lookup order: `MEL_BEDROCK_REGION`, then `AWS_REGION`, then `AWS_DEFAULT_REGION`.
If none is set, `/healthz` still works and reports `"region": null`, but any
Bedrock call fails with a message naming these variables. Phase 0 was verified
in `us-west-2`.

Credentials come from the standard boto3 chain (environment, `~/.aws`, SSO, or
an IAM role). Nothing in this repo stores them.

## Run

```bash
.venv/bin/uvicorn mel_agent.main:app --reload --port 8000
curl http://127.0.0.1:8000/healthz
```

Docker (credentials and region are passed through from your shell by name).
**The image has not been built or run yet**: Docker was not available on the
development machine.

```bash
docker compose up --build
```

## Test

```bash
.venv/bin/pytest                 # offline suite; no AWS calls, no cost
```

The live Bedrock test is excluded by default. To run it (one paid call, a few tokens):

```bash
MEL_RUN_BEDROCK_SMOKE=1 .venv/bin/pytest -m bedrock
# or
.venv/bin/python scripts/bedrock_smoke.py --yes
```

`bedrock_smoke.py` checks settings, region, pricing file and credentials before
calling AWS. Exit codes: `0` success, `1` the AWS call failed, `2` not confirmed
or misconfigured.

## Bedrock

```bash
.venv/bin/python scripts/discover_bedrock.py --filter anthropic
.venv/bin/python scripts/fetch_bedrock_pricing.py --region us-west-2 [--require <model-id>]
```

`fetch_bedrock_pricing.py` refuses to write an empty or incomplete table (every
Haiku/Sonnet/Opus 5.5 `us.` and `global.` profile, plus any `--require`, must have
input and output prices). It writes atomically, and on failure leaves the
existing file unchanged and exits `1`.

Default model: `us.anthropic.claude-haiku-5-5` (US cross-region inference
profile). Change with `MEL_BEDROCK_MODEL_ID`.

Retries: `MEL_BEDROCK_TOTAL_MAX_ATTEMPTS` (default `3`) is the **total** number
of requests per call, including the first one.

## Spending controls

- Hard maximum `MEL_BUDGET_MAX_USD=250`; operational stop `MEL_BUDGET_STOP_USD=225`.
- Every call returns input/output/cache token counts and an estimated USD cost
  from `config/bedrock_pricing.json`. A model with no pricing entry reports
  `None`, never a guessed number.
- The persistent spend ledger and automatic stop are a later phase.
