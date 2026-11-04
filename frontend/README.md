# FarmerChat MEL Survey Agent — Operator + Phone demo UI

React + TypeScript + Vite front end for Team 41's Digital Green hackathon entry.
A split-screen demo: operator console (left) and farmer phone simulator (right),
tied by a simulated clock, with JAAKBOT (browser voice). **Synthetic data,
simulated delivery. Nothing is sent to real farmers.**

## Quick start

```bash
cd frontend
npm install
npm run fixtures     # build public/fixtures from the pack + a real offline backend run
npm run dev          # Vite dev server (runs on fixtures by default)
```

### Run against the live backend

Start the backend offline with the template provider (no paid inference), then
set `VITE_API_BASE` and enter the operator token in the UI (kept in memory only).
From the repo root, with the python venv, run uvicorn on `mel_agent.api:app`
(see `.env.example`) with `MEL_OPERATOR_TOKEN` set and `MEL_PROVIDER=template`. Then
set `VITE_API_BASE` in `frontend/.env` to the backend's URL.

The five live endpoints used are: `GET /health`, `POST /v1/surveys`,
`GET /v1/surveys/{id}`, `POST /v1/surveys/{flow_id}/responses`, `GET /v1/follow-ups`.
If the API is unreachable the UI auto-falls back to fixtures and shows a banner.

## Scripts

| Script | Purpose |
|---|---|
| `npm run dev` | Vite dev server |
| `npm run build` | Type-check (strict) + production build |
| `npm run lint` | ESLint (bans `innerHTML`/`dangerouslySetInnerHTML`) |
| `npm run test` | Vitest unit + fixture schema validation |
| `npm run e2e` | Playwright end-to-end |
| `npm run fixtures` | Regenerate `public/fixtures` from the pack + offline backend |

## Swapping in your own data (drop-in, zero UI code changes)

The UI reads everything through the `DataSource` interface (`src/data`). Three
implementations exist: `LiveApiSource` (real API), `PackSource`/`FixtureSource`
(the files under `public/fixtures`). To swap data:

1. **Point at a live API:** set `VITE_API_BASE` and pick "Live API" in the data-source
   chip. No code changes.
2. **Replace fixtures:** regenerate with `npm run fixtures`, or drop your own
   files into `public/fixtures/` keeping the same folder shape (`scenarios/`,
   `outcomes/`, `schemas/`, `reports/`, `generate/`, `seed/`, `scenarios-index.json`,
   `ingest-stats.json`). The schema-validation test
   (`npm run test -- tests/fixtures.schema.test.ts`) enforces that every
   survey/response/handoff still validates against the six pack schemas.

Nothing in `public/fixtures` is hand-authored: scenarios/outcomes/schemas/reports
are copied from the participant pack, and `generate/*.json` is captured from a real
offline `mel_agent` run. Survey provenance is therefore "template, offline"
and is labelled as such in the UI; it is never presented as Bedrock output.

## Known limits (honest)

- The simulated clock, broadcast diffs, pipeline batch counts, stats, budget and
  the human queue have **no backend endpoint in this repo**; they are computed in
  the UI from the pack/fixtures and are labelled "simulated in UI".
- Hindi survey text is rendered verbatim from the backend; UI chrome strings are
  marked "needs native-speaker review".
- JAAKBOT Hindi speech recognition depends on the browser; where unsupported the
  keypad and simulate-speech chips keep the flow working.
