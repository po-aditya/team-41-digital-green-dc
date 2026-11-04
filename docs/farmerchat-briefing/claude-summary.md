# FarmerChat Contextual MEL Survey Agent (MVP): Source Review

## Overall intent

Both documents describe a hackathon MVP. The MVP is a MEL (Monitoring, Evaluation and Learning) agent. It reads insights that FarmerChat already extracts from farmer conversations and turns them into short, personalized, tap-based follow-up surveys. Each survey is timed to the crop calendar and the advice's action window, then handed to a scheduler and broadcaster [Vision — Executive Summary].

The stated priority is survey quality, demonstrated through evaluation. Infrastructure and scale are secondary [Technical — Hackathon Approach and Expectations]. The work uses fully synthetic data only. There is no FarmerChat access, no Digital Green AWS access and no real farmer data [Technical — Hackathon Approach and Expectations; Vision — Business Constraints].

## Vision document

**Problem.** Today, evidence that farmers adopt the advice comes from field surveys and RCTs on small samples. These are expensive and cannot cover about 2.2M farmers. Earlier digital surveys were broadcast: every farmer got the same questions regardless of context, which yields little information and erodes trust [Vision — Problem Statement].

**Users** [Vision — Target Users and Stakeholders]:
- **Small-scale farmers in Bihar** need a few quick, relevant taps at a sensible time.
- **The MEL team** needs adoption and outcome data per recommendation.
- **Product and AI teams** need a clean contract into the broadcaster and app.
- **An external evaluation agency** needs a consistent, auditable collection method.

**Roadmap context.** The MEL Agent is the hackathon focus. NightSync, SeasonPlanner and FarmWatch are future phases [Vision — The Background Agent Vision].

**Design principles** [Vision — Design Principles]:
- One farmer, one context.
- Short and tappable.
- Ask at the right time.
- Quality before volume: no survey is better than an irrelevant one.
- Evaluate before scheduling.
- Contract over framework.
- Language passed as a BCP 47 parameter.

**Safety** [Vision — Safety Tenet]:
- Surveys must never collect personal information.
- Surveys must not give new advice or contradict the advice already given.
- Negative-outcome responses should be routed back for follow-up.

**Evidence status.** Surveys capture self-reported adoption and outcomes. They do not prove causal impact. The source says RCTs "stay as the verifier", and replacing RCTs is explicitly out of scope [Vision — Business Drivers; Vision — Features Explicitly Out of Scope].

## Technical document

**Stack** [Technical — Programming Languages; Technical — Frameworks and Libraries]:
- Python 3.12+ is required. SQL/PostgreSQL is permitted.
- Google ADK (Digital Green's production framework) is preferred. Strands or another framework is acceptable if the REST/JSON contract is met.
- Suggested libraries: Boto3 with the Bedrock Converse API, Pydantic or JSON Schema, FastAPI, Streamlit, and CDK or Terraform.

**Models.** Amazon Bedrock is required, with the model behind an abstraction so it can be swapped. Tiering (a small model for checks, a larger one for generation) is suggested for exploration. Tokens, estimated cost and time should be logged per survey and per batch. Which models are enabled is still to be confirmed [Technical — Models and AI Services].

**Hosting.** Either AgentCore Runtime or containers (portable to Digital Green's EKS). If a database is used, it should be RDS or Aurora PostgreSQL. No real messages may be sent [Technical — Infrastructure Preferences].

**Architecture.** A reference architecture figure exists, but only its placeholder appears in the supplied text. I have not inspected the figure. The text allows simplification, for example a single process with a loop standing in for the scheduler [Technical — Reference Architecture].

**Data** [Technical — Provided Datasets; Technical — Core Data Contracts; Technical — Simulated Clock]:
- **Insights:** about 5,000–10,000 rows for 200–500 synthetic Bihar farmers in the rabi season (Nov–Mar). Conversations are in Hindi; insights are in English.
- **Golden dataset:** format and size to be confirmed.
- **Crop calendar:** source to be confirmed.
- **Contracts:** draft insight, survey and response JSON contracts, including `send_window`, `source_insight_ids`, `rationale` and `self_eval`.
- **Clock:** a shared simulated clock, with a manual trigger for every scheduled step.

**Evaluation** [Technical — Evaluation and Quality Measurement]:
- **Method:** hill-climbing against the golden dataset.
- **Dimensions:** relevance, timeliness, format, safety and speed.
- **Checks:** deterministic checks for format and timing; LLM-as-judge for relevance. Whether an MEL rubric exists is unconfirmed.
- **Language:** English is the evaluation baseline. Hindi is human-reviewed.

## Proposed end-to-end workflow

1. Ingest synthetic insights and query them by farmer, crop, topic and date [Vision — Features In Scope].
2. Decide whether an insight is eligible, then generate a survey per insight or group of insights in the requested language.
3. Self-evaluate (schema plus relevance). Failing surveys are not scheduled.
4. The scheduler assigns a send window from the crop calendar and action window, then applies a per-farmer frequency cap.
5. A broadcaster stub on the simulated clock delivers due surveys to a simulated app, which renders tap items and records answers.
6. The evaluation harness scores the outputs and the team iterates [Vision — MVP User Journeys].

Journey 1 is a mustard aphid case: a two-day action window, a three-item Hindi survey, and a send window 5–7 days after the advice. The draft contract's example dates are consistent with this [Technical — Core Data Contracts]. Journey 3 (negative-answer follow-up) is a stretch.

## MVP scope and success criteria

**Must Have** [Vision — Features In Scope]:
- Insight ingestion
- Survey generation agent
- Survey JSON contract
- Self-evaluation step
- Evaluation harness
- Survey scheduler

**Should Have:**
- Broadcaster stub and simulated app
- Hindi surveys
- Latency and cost telemetry

**Exploratory:**
- Response write-back
- Negative-outcome follow-up
- Alternative channels such as voice or chat

**Success criteria** [Vision — MVP Success Criteria]:
- Ingest the full dataset.
- Produce valid, advice-specific JSON with consistent send windows.
- Report golden-dataset scores for relevance, timeliness and format.
- Measure generation time.
- Run the scheduler with a frequency cap, plus the broadcaster stub and simulated app.
- Block failing surveys from scheduling.
- Run English end to end and produce Hindi when passed `hi-IN`.

**Definition of Done** adds: at least one improvement iteration, verification that invalid or low-scoring surveys are not scheduled, and publication of code, IaC, harness and README as open source [Vision — MVP Definition of Done].

**Pilot vs. hackathon.** The hackathon cohort is 200–500 *synthetic* farmers. A ~10,000-farmer real pilot is only *intended* by Digital Green "if quality holds" [Vision — Executive Summary]. No pilot has been authorized or run, and the sources report no implementation progress or results.

## Dependencies and open decisions

**Items to confirm** [Technical — Models and AI Services; Technical — Evaluation and Quality Measurement; Technical — Provided Datasets; Vision — Key Risks]:
- Bedrock models and region
- Golden dataset format and size
- Whether an MEL rubric exists
- Crop calendar source
- Agreement on the survey JSON with Digital Green's agent-to-UI format before the event

**Explicit open questions** [Vision — Open Questions]:
- How many items per survey, and which question types work best?
- Which insights deserve a survey, and should several be combined?
- How should send windows be derived for weather-dependent advice?
- Which automatic checks best predict acceptance by the golden dataset and MEL reviewers?
- How should generation be batched or parallelized?
- (Stretch) How should answers become adoption and outcome measures comparable with RCTs?

**Key risks:**
- Data arriving late (high impact); the mitigation is to generate a sample from the schema.
- Hindi quality being hard to judge.
- A schema mismatch with the agent-to-UI format (high impact) [Vision — Key Risks].

## Tensions and gaps to resolve

*All points below are my review observations, not source statements.*

**Contradictions between the success criteria and the priority table:**
- The success criteria require broadcaster delivery to a simulated app, but that feature is **Should Have**.
- The success criteria require Hindi output for `hi-IN`, but Hindi is **Should Have**.
- Generation time must be "measured" (and reported, per the DoD), but latency/cost telemetry is **Should Have**. The Technical doc also states token and cost logging without qualification.
- The DoD requires only Must Haves, so a team could meet the DoD while missing stated success criteria.

**Safety:**
- The Safety Tenet says negative-outcome responses *should be routed back*, but that feature is **Exploratory**.
- Safety is an evaluation dimension in the Technical doc but is absent from the scored success criteria (relevance, timeliness, format only).

**Self-evaluation scope.** The design principle lists schema, relevance *and language*. The feature table lists only schema and relevance.

**Undefined thresholds.** None of the following are defined in either source, and none should be assumed:
- the "low-scoring" cutoff
- the relevance threshold
- the frequency-cap value (Journey 1's "that week" implies weekly but is not specified)
- the item-count limit (format checks reference "limits", yet item count is an open question)
- "eligible" insight criteria

**Granularity.** The success criteria say "for each eligible insight", while the feature table allows a group of insights. The open question on combining insights is unresolved.

**Response handling overlap.** The simulated app "records answers" (Should Have), but response write-back is Exploratory, and the draft contract already defines a response object.

**Evaluation validity.** Both datasets are synthetic, so golden-dataset scores show agreement with Digital Green's expectations, not real farmer acceptance or adoption.

`★ Insight ─────────────────────────────────────`
- The priority table and the success criteria were evidently written separately. Before the event, reconcile them by either promoting the broadcaster/app, Hindi and timing to Must Have, or relaxing the criteria.
- Agreeing on gating thresholds and the frequency cap with the MEL team early matters as much as the schema. Without them, "not scheduled if low-scoring" cannot be tested.
`─────────────────────────────────────────────────`
