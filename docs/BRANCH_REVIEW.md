# Team MVP and document review

Reviewed 4 November 2026 from the fetched branch tips. Exact source commits and
per-file SHA-256 hashes are in `integration-sources.json`. That manifest also lists
every integration edit and its reason. The contributor branches are preserved;
this review branch imports their files with explicit path mappings.

## What each branch contributes

| Source | Preserved location | Strength | Limitations and integration decision |
| --- | --- | --- | --- |
| `origin/main` | Existing `docs/` and `nothing.txt` | Uploaded vision, technical requirements, architecture diagram | Main had documents but no runnable application |
| `origin/mvp-in-phases/aditya` | Root `src/`, `tests/`, configuration, Docker, lockfiles | Full offline pipeline, SQLite persistence, operator auth, spending ledger, catalogue content checks, scheduler, follow-up queue | Primary application; model-generated wording constrained by catalogue; two documented golden-set disagreements; original README retained in `docs/source-readmes/aditya.md` |
| `origin/kevin/mockup` | `prototypes/kevin/`, shared root `data/` | Streamlit demo, phone mockup, model writer/judge, English/Hindi reports, full-dataset historical report | Separate experimental application; paid calls now require explicit opt-in and API requires operator token; no durable spend ledger or production identity system |
| `origin/feature/jeremiah-farmerloop` | `farmerloop/` | Deterministic foundation, feedback interpreter, outcome-grid conformance, simulated channel responses, Radar research notes | Separate library/demo; no durable cross-survey cap or opt-out enforcement; Radar is a proposal, not implemented |
| Remote and local briefing branches | `docs/farmerchat-briefing/`, `tests/briefing.acceptance.mjs`, `docs/source-snapshots/` | Feature briefing, independent design/security evidence, acceptance script | Conflicting historical briefing variants preserved as snapshots rather than overwritten |

FarmerLoop's branch also contains an older copy of Kevin's application. Its
non-FarmerLoop paths were compared against Kevin's latest branch; Kevin's latest
version includes additional batch tooling, relevance threshold changes, tests and
reports. The FarmerLoop subtree is imported from Jeremiah's latest branch, while
Kevin's latest branch is the source for the model-based prototype. No stale copy
is substituted for a newer one. Ten unique older root-file versions from that
branch are archived under `docs/source-snapshots/farmerloop-branch/`.

## Uploaded documents and supplied data

- **Vision Word document:** intact under `docs/Digital Green Foundation/`.
  Requires contextual, brief, tappable follow-ups; crop/action timing; evaluation
  before scheduling; synthetic data; an English baseline and parameterized Hindi.
  No production FarmerChat integration or real delivery is required.
- **Technical Word document:** intact beside the vision. Python 3.12+, Bedrock
  behind a swappable model abstraction, REST/JSON contracts, simulated delivery,
  measured quality/latency/tokens. Hosting is flexible; live AWS access is not
  necessary to validate the offline workflow.
- **Participant pack:** all 303 source files preserved at `data/participant-pack/`,
  including 6,999 practice insights, 150 golden cases, farmer/crop tables, six
  schemas, worked scenarios, channel renders and response outcomes.
- **Architecture and briefing:** preserved with their original evidence files.
- **Local `VISION.md`:** left untracked and untouched. Word `~$` files are temporary
  lock artifacts, not additional uploaded requirement documents. Existing tracked
  ones were preserved, and new lock artifacts are ignored.

## Why the runtimes remain separate

Both Kevin and Aditya use the import name `mel_agent` but implement incompatible
APIs, IDs, persistence and generation policies. Combining their module files or
importing both in one process would silently select the wrong implementation.
The workspace instead consolidates their sources and unchanged data, provides
one primary application, and runs the alternate demos in separate processes.
FarmerLoop response logic has not been connected to the primary application's
state machine; shared JSON Schema conformance alone does not establish matching
business semantics.

## Reproduce the primary workflow

From the repository root, follow the root README setup and offline commands.
The primary defaults to the included data pack, template provider, paid inference
off, and simulated channels. Set an operator token before starting the API.
The original upstream README is preserved for provenance; its old external pack
path and unpublished-branch status are superseded by this workspace README.

## Kevin prototype

Use a **separate environment** from the primary editable package to avoid the
shared `mel_agent` package name. From the repository root:

```sh
uv venv --python 3.12 prototypes/kevin/.venv
uv pip install --python prototypes/kevin/.venv/bin/python -r prototypes/kevin/requirements.txt
PYTHONPATH=prototypes/kevin prototypes/kevin/.venv/bin/python -m pytest -c /dev/null prototypes/kevin/tests
PYTHONPATH=prototypes/kevin prototypes/kevin/.venv/bin/python -m mel_agent.cli eval --name offline --rules-only
prototypes/kevin/.venv/bin/streamlit run prototypes/kevin/app/streamlit_app.py --server.address 127.0.0.1
```

The static phone mockup is `prototypes/kevin/mockup/index.html`. Historical model
reports are in `prototypes/kevin/reports/`; they were not regenerated here.
The default data path now points to the shared root pack. `MEL_PACK_DIR` still
overrides it. Model-dependent UI actions require `MEL_ALLOW_PAID_INFERENCE=true`.
The optional API additionally requires `KEVIN_OPERATOR_TOKEN` (at least 16
characters), sent in `X-Operator-Token`, for every `/v1/` route. `/health` is public.
Bind any local prototype server to localhost. The opt-in does not impose a budget;
use the primary application when durable spending controls are required.

## FarmerLoop

From the repository root, use its own project environment:

```sh
uv run --project farmerloop --extra dev python -m pytest -c farmerloop/pyproject.toml farmerloop/tests
uv run --project farmerloop python -m farmerloop.demo
uv run --project farmerloop python -m farmerloop.feedback_demo
```

`FARMERLOOP_PACK` overrides the shared-pack discovery. `--bedrock` explicitly
requests a live paid call and was not used for this validation.

## Requirements still awaiting proof or a product decision

- Hindi still needs review by a Hindi speaker; automatic schema/script checks
  do not establish language quality.
- Primary template evaluation uses deterministic relevance proxies. Kevin's
  recorded LLM-judge scores use different methods and cannot be ranked directly.
- The official rules and golden examples disagree about some send windows,
  season boundaries and no-survey reason codes. The primary documents its
  decisions in `CONTRACT_QUESTIONS.md`; the alternate prototypes differ.
- Kevin's API uses operator-trusted submitted follow-up annotations; it does not
  independently reconstruct response semantics. It now checks survey/farmer/
  source/language provenance and returns generic invalid-response errors.
- The primary is a sandbox with a shared operator secret, not production identity
  and role management. Alternate model-generated text has weaker safety checks.
- No production deployment, live farmer delivery, new paid inference, or
  independent agronomic/Hindi quality certification is claimed.
