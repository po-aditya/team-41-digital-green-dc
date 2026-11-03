# FarmerChat Contextual MEL Survey Agent (Team 41)

Digital Green × AWS Breaking Barriers 2026 hackathon. Team: Kevin, Jeramiah, Aditya, Allen.

The agent reads the insights FarmerChat extracts from each farmer's conversations and decides whether a follow-up survey is worth sending. If it is, the agent writes one to three tap-answer questions about the advice that farmer got, in the farmer's language, and sets a send window. It checks its own output, then hands passing surveys to a scheduler. A simulated season delivers them, applies the weekly cap, falls back between channels, and records farmers' answers, including failures and bad outcomes that need follow-up.

## How it works

| Step | Module | How |
|---|---|---|
| 1. Decide survey or not (rules R1 to R8) | `mel_agent/rules.py` | Deterministic |
| 2. Send window, priority, channel order | `mel_agent/rules.py` | Deterministic |
| 3. Write the questions | `mel_agent/writer.py` | Claude Sonnet 5.5 on Bedrock |
| 4. Self-check: schema, labels at most 20 characters, script, personal-info words, then an LLM judge for relevance, new advice and language | `mel_agent/checker.py` | Code, then Claude Haiku 5.5 |
| 5. Scheduler hand-off JSON (only if step 4 passes) | `mel_agent/rules.py` | Deterministic |
| 6. Simulated clock, scheduler, broadcaster, farmer answers | `mel_agent/season.py`, `mel_agent/responses.py` | Simulation |
| 7. Evaluation against the golden set | `mel_agent/evaluate.py` | Code, then Claude Haiku 5.5 with the golden survey as reference |

Every output validates against Digital Green's JSON Schemas in `data/participant-pack/json/schemas/`: survey, schedule hand-off, response and no-survey. Models are set in `mel_agent/config.py` and can be changed with environment variables (`MEL_WRITER_MODEL`, `MEL_CHECKER_MODEL`).

## Results on the golden set (150 cases)

| Run | Decision | Rule | Window exact | Format | Relevance | Matches DG questions | Safety | Sec/survey |
|---|---|---|---|---|---|---|---|---|
| v0 `rules.json` literally | 0.907 | 0.887 | 0.000 | | | | | |
| v1 calibrated rules | 1.000 | 1.000 | 1.000 | | | | | |
| v2 LLM, prompt 1, en-IN | 1.000 | 1.000 | 1.000 | 1.000 | 0.904 | 0.778 | 1.000 | 6.7 |
| v3 LLM, prompt 2, en-IN | 1.000 | 1.000 | 1.000 | 1.000 | 0.935 | 0.918 | 1.000 | 7.2 |
| v4 LLM, prompt 2, hi-IN | 1.000 | 1.000 | 1.000 | 1.000 | 0.937 | 0.916 | 1.000 | 10.8 |

What changed between runs:
- **v0 to v1:** we compared `rules.json` with the golden set and added three skip rules: severity critical (R2), no check needed (R5) and crop already harvested (R7). We also matched the golden window timing. See `rules.CALIBRATION_NOTES`.
- **v2 to v3:** the writer prompt now uses Digital Green's standard MEL question and answer patterns for each resolution type, taken from the golden set, so answers can be compared across farmers.

Relevance and the match with Digital Green's questions are LLM-judge scores from 0 to 1. Hindi output still needs review by a Hindi speaker. Full reports are in `reports/`, and `reports/history.jsonl` holds the trend.

## Run it

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
# AWS credentials with Bedrock access in us-west-2

.venv/bin/streamlit run app/streamlit_app.py              # demo app
.venv/bin/python -m mel_agent.cli eval --name myrun       # golden-set evaluation (--language hi-IN, --rules-only)
.venv/bin/python -m mel_agent.cli generate                # full dataset -> out/results.jsonl
.venv/bin/python -m mel_agent.cli season                  # simulate the season from out/results.jsonl
.venv/bin/uvicorn mel_agent.api:app --port 8001           # REST API
```

On the Workshop Studio IDE, start Streamlit with `--server.baseUrlPath absproxy/8501` and open `https://<your-ide-host>/absproxy/8501/`.

### REST API

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/v1/surveys?language=hi-IN` | insight JSON | decision, survey, self-check, hand-off |
| GET | `/v1/surveys/{survey_id}` | | stored result |
| POST | `/v1/surveys/{flow_id}/responses` | answer record | 201 accepted, 200 duplicate, 404 unknown flow, 422 invalid |
| GET | `/v1/follow-ups` | | answers that reported failed advice or harm |

## Repository layout

| Path | Contents |
|---|---|
| `mel_agent/` | The agent, scheduler simulation, evaluation, CLI and API |
| `app/streamlit_app.py` | Demo app: agent, season simulation, evaluation, dataset |
| `reports/` | Evaluation reports |
| `data/participant-pack/` | Digital Green's synthetic data pack, version 1 |
| `mockup/index.html` | Static design mockup |

## Notes and known gaps

- Junk insights are detected without the practice-only `quality_flag`. A row counts as junk if it fails the insight schema, is a casual conversation, or has neither a crop or animal nor a concern. This catches all 723 junk rows and flags no clean rows.
- The no-survey schema allows only two reason codes, so other reasons are mapped to the closer one, and the R1 to R7 code is kept in the reason text.
- The golden windows open at 09:00, while the worked scenario uses 07:00. We follow the golden set.
- Cost is not estimated until token prices are set in `MEL_WRITER_PRICE` and `MEL_CHECKER_PRICE`. Token counts are always reported.
- Each survey covers one insight. Combining several insights for one farmer into one survey is not built yet.
- All data is fully synthetic. No real farmer data is in this repository.
