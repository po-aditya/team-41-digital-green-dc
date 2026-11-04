# FarmerChat Contextual MEL Survey Agent — One-Day Hackathon Decision Briefing

*Review conducted using Gemini 4 Argon. Based strictly on the supplied Vision, Technical, and Public Repo Evidence documents. No code executed, no external sources queried, and no hackathon outcomes guaranteed.*

---

## 1. Baseline Scope vs. Enhancements

### Source Facts (`Vision` & `Technical`)
* **Must Have (Table Stakes):**
  1. **Insight Ingestion:** Load/query the synthetic dataset (5,000–10,000 English insights across 200–500 Bihar farmers, Nov–Mar rabi season).
  2. **Survey Generation Agent:** Generate short, contextual, tap-based surveys per eligible insight (or group of insights), parameterized by BCP 47 language code (`en-IN`, `hi-IN`). If an insight does not support a meaningful question, generate nothing.
  3. **Survey JSON Contract:** Emit valid Agent-to-UI JSON (`survey_id`, `farmer_id`, `source_insight_ids`, `language`, `send_window`, `items`, `rationale`, `self_eval`).
  4. **Self-Evaluation Gate:** Validate JSON schema, safety (no new agronomic advice, no PII), and relevance before scheduling; block failing surveys.
  5. **Survey Scheduler:** Derive `[not_before, not_after]` send windows from crop calendar + `action_window_days` and enforce a per-farmer frequency cap.
  6. **Evaluation Harness:** Score generated English baseline surveys against Digital Green’s golden dataset (relevance, timeliness, format, safety, speed) and demonstrate at least one hill-climbing improvement iteration.
* **Should Have:** Broadcaster stub + simulated tap UI on a shared simulated clock (with manual triggers); Hindi (`hi-IN`) survey generation; latency/token/cost telemetry per survey and batch.
* **Exploratory / Stretch:** Response write-back to insights; negative-outcome follow-up routing (Stretch Journey 3); alternative channels (voice/chat).
* **Explicitly Out of Scope:** NightSync/SeasonPlanner/FarmWatch agents, live FarmerChat/AgMCP integration, real message delivery, scale testing (100k users), languages beyond English/Hindi, and replacing RCTs.

---

## 2. Public-Code Compatibility vs. Production Claims

### Source Facts
* **Production Claims (`Vision` & `Technical`):** State that production FarmerChat on AWS uses Python 3.12+, Google ADK, ~20 MCP servers (including AgMCP), three agents (Alignment, Main, Insight Extractor), REST agent-to-agent calls, Agent-to-UI JSON, Amazon RDS for PostgreSQL, and is moving to Amazon EKS.
* **Public Code (`Public repo evidence` — [`DG_Open`](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/api/urls.py#L7-L13) at commit `5064d657`):**
  * Exposes a Django REST endpoint [`ChatAPIViewSet.get_answer_for_text_query`](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/api/views.py#L44-L86) with `authentication_classes = []`.
  * Calls OpenAI directly via `AsyncOpenAI` in [`make_openai_request`](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/rag_service/openai_service.py#L20-L49) and records prompt/completion tokens and timestamps in [`generate_response.py`](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/generation/generate_response.py#L59-L79).
  * Defines relational models in [`models.py`](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/database/models.py#L60-L341) including `Language` (`bcp_code`), `Messages`, and `FollowUpQuestion` (`ref_id`, `message`, `follow_up_question_type` as nudge/message, `sequence`).
  * Renders responses via `innerHTML` in [`index.html`](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/index.html#L532-L538), has an empty [`tests.py`](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/api/tests.py#L1-L3), and is licensed under GPL v3 in [`LICENSE`](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/LICENSE#L1-L6).

### Review Observations
* **Do not import or extend `farmer-chat/`:** The inspected public subtree represents an older OpenAI-based RAG monolith, not the Google ADK / Bedrock / 3-agent production architecture described in the `Vision` and `Technical` docs. It contains no MEL agent, scheduler, or evaluation harness.
* **Contract-first greenfield build:** Align strictly to the JSON data contracts in the `Technical` doc (`insight`, `survey`, `response`), which only conceptually share `bcp_code` and token/latency logging with the public repo. Avoid copying `farmer-chat/` code to prevent inheriting `innerHTML` XSS sinks, unauthenticated view patterns, or unintended GPL v3 viral licensing constraints.

---

## 3. Comparison of the Five Proposed Enhancements

| Feature Choice | Scope Tier (Source Fact) | Smallest 1-Day Demo (Observation) | Dependencies | Key Risks |
| :--- | :--- | :--- | :--- | :--- |
| **(1) Failed-advice follow-up** (simulated human-review case/status, no new advice) | **Exploratory** (Stretch Journey 3) + **Safety Tenet** | Deterministic rule on response write-back: if `adoption in {yes, partly}` and `outcome == negative`, create a local case object (`status: "pending_agronomist_review"`) shown as a badge. | Response capture, stable option IDs (3 & 4). | Generating remedial LLM advice violates the Safety Tenet; building a complex ticketing workflow wastes time. |
| **(2) Season-aware timeline & simulated clock** (windows, frequency caps, grouping) | **Must Have** (Scheduler) + **Should Have** (Simulated Clock/Broadcaster) | Streamlit date stepper (Nov–Mar) + manual trigger showing insight grouping, `[not_before, not_after]` calculation, frequency-cap suppression, and due surveys. | Insight ingestion, crop calendar lookup, `send_window` schema. | Over-building real cron/queue infrastructure when a single-process loop/state filter suffices. |
| **(3) Adaptive short fixed-option survey** (branching on adoption to outcome vs. barriers) | **Must Have** (Survey Generation & JSON Contract refinement) | 3-item JSON survey: `q1` (adoption: `yes`/`partly`/`no`), `q2_outcome` (shown if `yes`/`partly`), `q3_barrier` (shown if `no`). | Optional `show_if` property on `survey.items` (or UI-level conditional rendering). | Breaking strict Golden Dataset schema checks if extra fields are disallowed—keep `show_if` optional or standard. |
| **(4) Hindi farmer tap view + English MEL view** (stable IDs; voice stretch only) | **Must Have** (BCP 47 + Contract) + **Should Have** (`hi-IN` + UI) + **Exploratory** (Voice) | Dual-pane Streamlit view: Hindi (`hi-IN`) tap buttons for farmer paired with English (`en-IN`) MEL view linked by invariant `survey_id`, `item_id`, and `option.id`. **Drop voice.** | Language-invariant IDs (`yes`/`no`/`partly`) separated from localized `label`/`prompt`. | LLM translating `option.id` into Hindi breaks aggregation; touching voice in 1 day derails core delivery. |
| **(5) Actionable MEL insight drilldown** (linked self-reported answers, no causal claims) | **Exploratory** (Response write-back) + **MEL Stakeholder Need** | Read-only summary table grouping responses by `crop`/`topic`/`resolution_type` (adoption rate, top barrier, flagged failures) with drilldown to `insight_id`. Label as *observational/non-causal*. | Response write-back, invariant option IDs from (3) and (4). | Over-claiming RCT-level causality (violates Vision doc) or spending hours on complex BI charting. |

---

## 4. Recommended One-Day Combination & What to Omit

### Recommended Cohesive Combination (Observations)
Build the **Must Have Evaluation & Generation Core first (Morning)**, then layer a **tight, unified 4-part contract loop (Afternoon)** combining **(2) + (4, text-only) + (3) + lightweight (1 & 5)**:
1. **Core + (2) Season-Aware Scheduler & Clock:** Directly proves Must Have scheduling criteria (crop calendar + `action_window_days`, per-farmer frequency cap, insight grouping, and blocked low-score surveys) via an interactive Nov–Mar simulated clock.
2. **(4) Bilingual Stable-ID Contract (`en-IN` + `hi-IN`, No Voice):** Generate English surveys for the Golden Dataset evaluation harness and Hindi labels (`hi-IN`) for the simulated farmer tap UI, sharing invariant IDs (`item_id: "q1"`, `option.id: "yes" | "no" | "partly"`).
3. **(3) Standardized 3-Item Tap Pattern (Adoption $\rightarrow$ Outcome / Barrier):** Standardize generated surveys into 3 fixed-option items (`q1` Adoption, `q2` Input/Barrier, `q3` Outcome) matching Journey 1. Render conditionally in the tap UI based on `q1`.
4. **Rule-Based (1) & (5) Write-Back Table (60-minute cap):** When a farmer taps answers in the simulated UI, write back the response JSON. If `q1 != "no"` and `q3 == "not_reduced"`, flag a static `pending_agronomist_review` status row (Feature 1, zero LLM calls, zero agronomic advice) inside a simple observational MEL summary table linked to `insight_id` (Feature 5).

### What to Omit Completely in a One-Day Hackathon
* **Voice / Audio / Chat channels (Stretch in 4):** High integration friction, zero impact on Golden Dataset scores.
* **External Databases & Container Orchestration:** Skip RDS/PostgreSQL setup and EKS/Docker deployment unless trivial; use in-memory/JSON/SQLite state behind a clean Python interface and FastAPI + Streamlit in a single process.
* **Multi-agent frameworks if unfamiliar:** If the team does not already know Google ADK or Strands Agents SDK, use plain Python 3.12 + `boto3` Bedrock Converse API + Pydantic + FastAPI. The `Technical` doc explicitly permits any internal structure that meets the REST and JSON contract.

---

## 5. Evaluation Baseline (Mandatory Table Stakes)

### Source Facts (`Vision` & `Technical`)
Evaluation is the primary judging criterion. Your harness must run across the synthetic dataset, compare against the golden dataset in **English (`en-IN`)**, and report at least **one hill-climb iteration** (Baseline Run $\rightarrow$ Prompt/Gate Change $\rightarrow$ Improved Run) across five dimensions:
1. **Format (Deterministic):** Pydantic/JSON Schema validation, tap-only item types (`single_choice`), item count within bounds, valid BCP 47 language code, and presence of `source_insight_ids` and `send_window`.
2. **Timeliness (Deterministic):** Verify `send_window.not_before` and `not_after` align with `insight.created_at` + `action_window_days` and crop calendar stage, and verify per-farmer frequency cap compliance.
3. **Safety (Deterministic + Judge):** Verify no PII is requested and no new or contradictory agronomic advice is given.
4. **Relevance (LLM-as-Judge):** Rubric-scored check that `items` specifically address the farmer's `crop`, `topic`, `advice_summary`, and `resolution_type` (and verify non-eligible insights produce no survey).
5. **Speed & Cost Telemetry (Deterministic):** Log wall-clock latency (per survey and full batch), prompt/completion tokens, and estimated cost; verify surveys failing `self_eval` are blocked from scheduling.

---

## 6. AWS Implementation Guidance

### Source Facts & Verification Guardrails
* **Mandatory Service:** **Amazon Bedrock** accessed via `boto3` **Bedrock Runtime Converse API** behind a model-abstraction wrapper so model IDs can be swapped without code changes.
* **Model Tiering (Suggested in `Technical`):** Use a smaller/faster Bedrock model for insight eligibility filtering and pre-schedule self-evaluation checks, and a larger Bedrock model for survey generation and LLM-as-judge scoring.
* **Optional Services (Must Independently Verify in Workshop Studio Account):**
  * *Bedrock Model IDs & Regional Quotas:* Confirm with event staff which region and specific models are enabled and check rate limits before batching 5,000–10,000 insights.
  * *Amazon Bedrock AgentCore Runtime / RDS for PostgreSQL / AWS CDK or Terraform:* Mentioned as acceptable/optional in `Technical`, but verify Workshop Studio IAM permissions before provisioning; a local/single-instance FastAPI + Streamlit app with IaC templates in the repo satisfies the MVP contract with far lower day-one deployment risk.

---

## 7. Unresolved Decisions to Confirm Immediately with Organizers

1. **Exact Schemas & Golden Dataset Format:** What is the exact JSON schema of the provided Golden Dataset and Crop Calendar, and does the schema validator allow an optional `show_if` field on `survey.items` for branching (Feature 3)?
2. **MEL Judge Rubric:** Does Digital Green provide an existing LLM-as-judge prompt/rubric for Relevance, or must the team author it?
3. **Eligibility & Grouping Rules:** Which `resolution_type` values (e.g., `wait_and_watch`) or topics should be skipped ("generate nothing"), and what is the exact time window and per-farmer frequency cap for combining multiple insights into one survey?
4. **Weather-Dependent Send Windows:** Since live weather/AgMCP is out of scope, what deterministic offset rule should the scheduler use when `advice_summary` is conditional on weather (e.g., *"spray within 2 days if no rain"*)?
5. **Batch Execution Requirement:** For the 5,000–10,000 insight run, is evaluating on the Golden Dataset subset plus a timed/extrapolated batch sample acceptable if Workshop Studio Bedrock throttling limits full-dataset generation?
