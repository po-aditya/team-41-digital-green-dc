# Consolidation security review

Reviewed independently on 4 November 2026 for the local consolidation branch.
No new blocking security finding was identified within the sandbox scope below.
This is a source review and targeted verification, not a production security
certification or proof that the applications contain no vulnerabilities.

## Scope and checks

- Read the current Kevin, FarmerLoop and phased MVP branch implementations,
  then reviewed the active consolidated application code and integration edits.
- Parsed 82 active application Python files with Python's AST. The common
  dangerous-call scan found no `eval`, `exec`, unsafe pickle/YAML loading,
  `os.system`, `shell=True`, or disabled TLS verification calls. Test fixtures
  and historical source snapshots were not treated as active applications.
- Scanned source and documentation for AWS access-key and private-key patterns.
  Matches were deliberate secret-disclosure test canaries; no apparent real
  credentials were identified. Pattern scanning cannot establish credential
  absence exhaustively.
- Verified all 510 source entries marked unmodified at the time of review
  against their SHA-256 manifest hashes, with no mismatches. This includes the
  supplied documents/data; the manifest also identifies intentional edits.
- Confirmed Docker Compose binds the primary API to localhost and mounts the
  included participant pack read-only. The Docker build context remains an
  allow-list. Docker build/runtime behavior was not exercised.
- Reviewed the primary operator-token dependency, disabled-by-default paid
  inference, budget-ledger path, local-only JSON Schema references, and closed
  question catalogue. Alternate `mel_agent` packages remain separate runtimes.
- Reviewed Kevin's HTML rendering: dynamic phone questions/messages are escaped.

## Independent verification

The primary security, model-key disclosure, pricing-error hygiene and packaging
tests passed: **163 passed** on the temporary validation environment.
The first invocation used a relative import path, which failed for subprocesses
that intentionally change working directory. Re-running with an absolute source
path passed all tests; no code change was needed for that invocation issue.

Separate direct Kevin probes verified:

- Public health remains available without a token.
- Each of the four protected route forms refuses access when the operator token
  is unset; a configured token rejects missing/wrong credentials and permits an
  authorized read.
- Paid inference is refused before client construction when not explicitly
  enabled. No AWS call or credential lookup was made by these probes.
- An injected generation failure returns the generic API error and does not
  disclose the injected diagnostic canary.

The dedicated Kevin security regression tests also passed independently:
**11 passed**. The full-suite validation report records the broader test counts.

## Repairs verified in this consolidation

Kevin's previously anonymous record/generation API now requires a configured
operator token of at least 16 characters, compared in constant time. The live
model wrapper requires explicit paid-inference opt-in before constructing a
credential-bearing client. Submitted answer records must match the stored
survey's farmer, source insights, language and survey identity. Invalid response
errors and API generation failures return generic messages.

## Inherited sandbox limitations

- The primary and Kevin use shared operator secrets, without production identity,
  per-user roles, token rotation, request quotas or per-caller audit. Keep local
  servers on localhost; no public deployment was reviewed.
- Kevin's explicit paid opt-in is not a durable budget limit. Its existing
  retries may multiply paid calls. The primary's ledger applies only to its own
  runtime and cannot meter another prototype or AWS console activity.
- Kevin trusts operator-submitted response semantics after schema/provenance
  validation; it does not reconstruct every follow-up annotation from answers.
  Its stores are in-memory and are not coordinated with the primary database.
- Kevin and FarmerLoop use weaker model-output and content-quality checks than
  the primary closed catalogue. Their model output is not certified safe or
  correct; Hindi and agronomic meaning still require qualified human review.
- FarmerLoop's explicit `--bedrock` demo can make a paid call; its live generator
  has no durable spending ledger. Its cap/opt-out limitations remain documented.
- Prototype dependency ranges are not independently locked. No online dependency
  vulnerability database audit, external penetration test, live AWS request,
  real farmer delivery or production assessment was performed.

These limitations do not block review of the local, offline, synthetic-data
workspace. They must not be interpreted as approval for production deployment.
