# Persistent scheduling protections

Implemented for the authorized backlog chunks 1 and 2. The earlier UI/timing
checkpoint was saved to `feature/jeremiah-farmerloop` as `c066bdf` before this
implementation began. This increment adds an offline service and demonstration,
not real messaging or the next interactive UI checkpoint.

## What is implemented

`src/farmerloop/scheduler.py` provides a SQLite-backed `Scheduler`. It reuses
`schedule.build_handoff`, `respond.build_response`, the existing simulator and
official outcome definitions. It does not copy the teammate `mel_agent` scheduler
or change teammate files, official schemas or participant data. No dependency
was added; SQLite is in Python's standard library.

- Immutable queued jobs, attempt reservations, final response snapshots,
  counted surveys, opt-outs and decision history survive closing/reopening the
  process. SQLite schema version 1 is initialized transactionally.
- One distinct survey per farmer in the rolling seven-day interval, across
  channels, excluding the current survey when checking a retry.
- High priority bypasses the weekly cap but counts once the survey is shown or
  its official response outcome counts. High priority never bypasses opt-out.
- Opt-outs block future jobs and already queued retries across all five
  channels. Declining one survey does not opt a farmer out of future surveys.
- Every claim rechecks due time, sending hours, window closure, expiry, cap and
  preferences. Every enqueue reruns the input/eligibility/quality/window gates.
- Transactions serialize competing claims: two connections cannot claim the
  same attempt or reserve two normal surveys for the same farmer concurrently.
- Replaying identical immutable submissions/observations does not create more
  jobs or cap events. Conflicting content is rejected rather than overwritten.
- Confirmed failed deliveries use their official cap flags; they do not count
  where the supplied rules say they should not. Known failures release the
  unknown-attempt reservation and permit rule-directed retry/fallback.
- Accepted answers and opt-out observations require the expected farmer
  identity. Wrong-identity outcomes cannot change preferences. External adapter
  authentication is still a future integration requirement.

## Deliberate policy choices

### Time and counting

All operations receive an explicit timezone-aware clock. Times are converted to
IST. A run's clock is persisted and cannot move backwards; separate runs allow
independent simulated timelines. Future response/display observations are rejected.

The cap interval is **(now minus seven days, now]**. At exactly seven days the
old count is outside the interval. A retry/fallback of a survey does not create
a second count or move its first-count timestamp forward. Other recent surveys,
including high-priority ones, still affect a normal-priority retry's cap check.

`acknowledge_shown` counts an actual confirmed display before any answer arrives.
Otherwise the official `counts_toward_cap` outcome determines counting. The first
available display (`opened`) or answer timestamp is used; when neither exists,
`recorded_at` is a conservative fallback. That fallback is an explicitly chosen
accounting time, not a claim that the display time is known. It can defer another
survey longer than the unknown actual display time would have required.

Permission checks and the persisted clock retain microsecond precision. The
official response schema permits only whole-second timestamps, so an authorized
attempt's reported send time is projected to that precision **after** checking
the boundaries. Rounding cannot authorize sending after the window closes.

### Reservation is not delivery

`claim` returns `claimed` once and marks the attempt in flight. It does not send
a message. Repeated calls return `in_flight`, never a new send authorization.
An unresolved attempt reserves capacity for its farmer until a valid outcome
or confirmed display is recorded. Unknown delivery is not treated as failure.

After a crash, the operator/adapter must reconcile the original attempt using
known observations. There is no automatic lease expiry that could resend a
message whose delivery is unknown. This favors avoiding duplicate asks over
availability. A genuinely unresolved attempt can therefore hold a normal job;
inspect the decision log rather than deleting history to unblock it.

This is not an exactly-once real-network-delivery guarantee. A production
transport needs idempotency support and receipt/reconciliation logic. An
already claimed attempt cannot be unsent by a later opt-out; future claims and
retries are blocked. This checkpoint has no network transport at all.

### Retries and late answers

For explicit failures, official `retry_decision` and `retry_after_minutes` drive
the next attempt. A retry checks all scheduling guards again. Same-channel
attempts are limited to three by default, a documented operational choice
rather than a supplied official limit. Configuration cannot exceed the response
schema's maximum of five attempts per channel. Exhaustion ends that job.

No-answer timeouts are not inferred merely because time advanced. An adapter
must supply a truthful final outcome; unobserved delivery stays unresolved.
The handoff's generic channel wait periods do not fabricate an outcome or
automatically trigger a second delivery while the first remains unresolved.

Accepted answers at/after expiry are rejected; a supported stale outcome can
still be recorded without accepted answers. If answer time is missing, recording
time is used conservatively for this check. There is no full late-response
reconciliation/integration service in this checkpoint.

### Storage and isolation

Each database can contain isolated `run_id` namespaces. Counts, preferences,
records and clock are shared within a run, never across runs. An eventual
deployment must use a stable campaign/state namespace; creating a new run on
every request would discard the effective history and is not supported usage.
Cross-campaign preference sharing needs an explicit production design.

The store fingerprints the supplied rules, outcome definitions, response schema
and configured retry limit. A changed policy cannot silently reuse the same run; use an
explicit migration/reviewed new run. Unknown database schema versions fail closed.
Use a dedicated SQLite file, one connection per worker/thread and a local disk.
This is not a multi-host production database.

`reset_demo(confirm_run_id=...)` requires an exact run ID beginning `demo-` and
clears only that run. Default/non-demo runs cannot use it. Reset is for fictional
test data only; no re-subscription operation is implemented. State files under
`state/` and `*.sqlite3*` sidecars are ignored by Git.

## Run the offline demonstration

From `farmerloop/`, using the installed environment:

```bash
python -m farmerloop.scheduler_demo
python -m farmerloop.scheduler_demo --json
python -m farmerloop.scheduler_demo --db state/demo.sqlite3
```

The no-argument command uses a temporary database and reopens it during the
demonstration to verify restart behavior. `--db` retains it after exit. Reusing
a populated demo run requires choosing another `--run-id demo-another` or an
explicit reset:

```bash
python -m farmerloop.scheduler_demo --db state/demo.sqlite3 --reset
```

In this workspace, replace `python` with
`/workspace/scratch/farmerloop-venv/bin/python`.

Expected story: one normal survey succeeds; a second is capped; high priority
can proceed; opt-out stops further asks; a different farmer's failed delivery
does not consume their cap; restart retains both opt-out and in-flight state.
The final demo has four reserved attempts, three counted surveys and one opted-out
farmer. All identities and interactions are explicitly synthetic.

## Service interface for the next checkpoint

| Method | Role |
|---|---|
| `enqueue(insight, survey, window, now=...)` | Validate and store one immutable job |
| `claim(survey_id, now=...)` | Reserve one permitted attempt or explain defer/drop |
| `acknowledge_shown(attempt_id, shown_at=..., verified_farmer_id=..., now=...)` | Count an observed display immediately |
| `complete(attempt_id, items=..., timestamps=..., recorded_at=..., answered_by=..., now=..., event=...)` | Derive and atomically ingest a final response from observations |
| `complete_simulated(attempt_id, case, now=...)` | Use the existing scripted offline simulator |
| `opt_out(farmer_id, verified_farmer_id=..., now=...)` | Apply an independently received, verified preference |
| `snapshot()` | Read stored jobs, attempts, counters, preferences and audit decisions |
| `reset_demo(confirm_run_id=...)` | Explicitly clear one synthetic demo namespace |

Identity arguments represent assertions by a trusted local adapter, not proof
of authentication. Do not expose these methods directly as an unauthenticated
public endpoint. Raw observations are passed to the existing response builder;
callers cannot directly provide derived cap flags, status or retry decisions.

## Verification and current integration limits

Verified on 2026-11-04: **513 tests passed** in 24.96 seconds (the prior 462
plus 51 new scheduler cases). All three existing offline CLI demos and the
English/Hindi fixed Radar UI smoke checks passed. The new scheduler CLI also
passed; its compact demonstration results are saved in
[`reports/scheduler-checkpoint.json`](../reports/scheduler-checkpoint.json).

New tests cover persisted caps/preferences, idempotent replay and conflicting
snapshots, separate worker connections racing for one or two jobs, all-channel
opt-out, high-priority exemption, exact cap boundaries, display counting,
record chronology, invalid identity/input, retry delay/exhaustion, window expiry,
run isolation, policy drift, reset isolation and a reopened-database demo.

The existing fixed Radar viewer and stateless CLI demos remain available. They
do not yet use this service, and their scripted outcomes do not demonstrate cap
enforcement. Connecting the temporary UI and Radar to this stateful path is the
next interactive-demo checkpoint. No background daemon, real messaging,
production authentication, paid AWS calls or teammate integration was added.
