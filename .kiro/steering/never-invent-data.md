---
inclusion: always
---

# Never invent data (farmerchat-ui)

The UI's credibility is the product. Every value a judge sees must trace to the
participant pack, a real backend run, or the reports/ directory.

## Rules
- No hand-written fixtures. `npm run fixtures` generates them from (a) the pack
  at `data/participant-pack/` and (b) a real offline backend run, and a Vitest
  test validates every generated survey/response/handoff against the pack's six
  JSON Schemas (`json/schemas/*.json`).
- When the real dataset arrives it is a drop-in: replace fixture files or point
  at the live API, zero UI code changes. Document the swap in the README.
- Backend ground truth in THIS repo (verified):
  - API endpoints: `GET /health`, `POST /v1/surveys`, `GET /v1/surveys/{id}`,
    `POST /v1/surveys/{flow_id}/responses`, `GET /v1/follow-ups`. Nothing else.
    No auth/CORS yet (CORS add is config-gated and allowed).
  - Pack path: `data/participant-pack/` (not the brief's ../ path).
  - 6 scenarios incl. 6-zero-tillage = NO survey. Each: insight, survey.en-IN,
    survey.hi-IN, schedule_handoff, render/{en-IN,hi-IN}/{app,web,whatsapp,
    telegram,voice}.json, responses/{channel}.json.
  - `json/outcomes/{channel}` has 3 records each (15 total), NOT 183.
  - insights.jsonl = 6999 rows. golden_set.jsonl = 150 cases.
  - reports/v0..v4: improvement iterations. v4 (hi) scores: decision/rule/
    recall/precision/window/channel/format/safety = 1.0, relevance 0.937,
    reference_intent 0.916, judged_surveys 95, status_counts scheduled 95 /
    no_survey 55 / rejected 0 / error 0, rule_mismatches [] . cost_usd = null.
  - Golden is reported as scores + status_counts, NOT a TP/FP/TN/FN matrix and
    NOT docs/reports/golden_evaluation.json (absent). Derive an honest
    2x2 from status_counts vs golden labels only if it can be computed from the
    `cases` array; otherwise show the real scores and label the rest
    "not evidenced here".
- Brief numbers that are NOT in this repo (TP93/FP0/TN55/FN2, 183 outcomes,
  specific mismatch ids, cost per survey) -> show "not evidenced here", never
  display them as fact.
- Backend behaviour is frozen. Allowed backend edits: CORS for the dev origin
  and optional static-serving of the built UI, both config-gated.
