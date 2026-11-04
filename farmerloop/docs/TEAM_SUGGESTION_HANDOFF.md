# FarmerLoop → Team project: suggested differentiators to carry forward

**Digital Green × AWS Breaking Barriers 2026 · Team 41 · 4 November 2026**

## Quick summary for the team

**Keep the team's existing product, and add a way for Digital Green to learn from feedback across different areas—and decide what to do next.**

The main ideas are:

- **Spot shared local problems.** If several farmers in an area cannot get the recommended seed, highlight that pattern for investigation.
- **Notice who we aren't hearing from.** Few complaints don't necessarily mean things are going well. Farmers may not be receiving or completing surveys.
- **Improve how we ask questions.** Look for places where questions are frequently skipped or answers are incomplete. Investigate wording, language, timing or delivery instead of assuming farmers don't care or don't trust the advice.
- **Recommend a practical next step.** Explain what Digital Green could investigate or improve, who could handle it, and which evidence supports the suggestion.
- **Check what happened afterward.** Record the team's follow-up and see whether the relevant problem or feedback gap improves.

For example: **District A reports difficulty getting seed, so investigate local access. District B barely responds, so investigate delivery and participation before judging whether the advice worked.**

We call this the **Regional Learning Radar**. A narrow version already works with simulated data; this handoff separates what can be reused today from ideas to add next.

**Decision:** Continue with the team's more complete application as the main product. Bring across the strongest FarmerLoop ideas, selected code and tests where useful. This is a suggestion handoff, not a request to replace the team's architecture or implement every item below.

**Recommended addition:** A **Regional Learning Radar with evidence-backed action recommendations** on top of the team's existing survey and response pipeline.

> Giving farmers advice is only half the job. Our product helps Digital Green understand what happened afterward, whose experience it is missing, and what to do next.

## 1. The idea in plain language

The Radar should help Digital Green answer four questions:

1. **What problems keep appearing in particular areas?** For example, farmers repeatedly report difficulty obtaining a recommended input.
2. **How well are we hearing from those areas?** Distinguish delivery failures, unanswered surveys, incomplete answers and actual reported barriers.
3. **What should we do about it?** Recommend a concrete investigation or service improvement, backed by evidence and reviewed by a person.
4. **Did our follow-up help?** Track what staff did and whether the relevant measure changed, without claiming that a simple before/after difference proves causation.

This creates two learning loops:

- **Agricultural learning:** Improve understanding of whether advice is practical, what barriers farmers report, and which reported outcomes need expert review.
- **Communication learning:** Improve the questions, language, timing and delivery methods used to hear from farmers.

The distinctive combination is **regional context + feedback gaps + traceable evidence + actionable next steps**. Survey generation, multilingual support and scheduling remain essential foundations; they should not carry the whole differentiation story. We have not assessed every competing team's product, so these are proposed differentiators, not claims of exclusivity.

## 2. Features and ideas worth preserving

“Implemented” below means demonstrated in FarmerLoop's synthetic/offline prototype, not integrated into the final team product or validated with real farmers.

| Idea | Why it matters | Current FarmerLoop status |
|---|---|---|
| **Regional agricultural patterns** | Surface recurring input-access difficulties or reported problems within comparable crop/advice contexts. | Implemented narrowly for a two-district wheat-seed access scenario. Other barrier and outcome categories need expansion. |
| **Missing-feedback blind spots** | A region with few complaints may simply be poorly represented. Never present silence as success. | Implemented: due-survey denominators, answer coverage, delivery failures, unknown delivery and evidence-gap findings. |
| **Regional participation and communication patterns** | Compare where surveys reach farmers, get answered, are declined or are abandoned; investigate differences across channels/languages. | Several underlying outcomes and metrics exist. A general engagement-analysis feature is proposed. |
| **Question and answer-quality patterns** | Identify skipped questions, invalid inputs and confusing question/option combinations; improve the collection process. | Response processing captures useful structured outcomes. Broad question-level regional diagnostics are proposed. Do not label farmers as “low quality.” |
| **Context-aware comparisons** | Compare similar crops, advice objectives, seasons and questions rather than misleading district averages. | Implemented cohort separation/comparison checks for the narrow seed-access demo. General semantic question mapping remains work. |
| **Evidence behind every finding** | Let a reviewer inspect the advice, survey, delivery/response records and counts supporting a conclusion. | Implemented source chains and evidence resolver. Include evidence for missingness and denominators, not only negative answers. |
| **Actionable recommendations** | Tell staff what to investigate, why, who could own it and how to check progress. | Basic evidence-backed review suggestions exist. Rich action cards, real assignment and follow-up measurement are proposed. |
| **Urgent individual reports plus regional clusters** | A single report of possible crop/livestock harm should reach a reviewer even if there is no regional cluster. | Response-level follow-up flags exist. Broader regional adverse-outcome analysis and an operational escalation workflow are proposed. |
| **Changes over time** | Detect emerging barriers or worsening feedback coverage; track results after staff action. | Proposed. Requires comparable time windows, stable question versions and sufficient observation time. |
| **Evidence-grounded AI investigation** | Use Bedrock to summarize retrieved evidence, identify missing information and draft a staff action. | Proposed for the Radar. Current Radar counts and findings are deterministic; an earlier live survey-generation call does not establish this feature. |
| **Knowing when not to ask** | Reduce unnecessary questions, respect opt-outs, wait for an appropriate action window and avoid repeated sending. | Eligibility/timing checks and persistent scheduler protections are implemented. Reuse tests or ideas selectively if the team's version already covers this. |
| **Accessible and adaptive feedback** | Short Hindi/English tap surveys; eventually read-aloud/voice support and appropriate branching when advice was not tried. | Bilingual tap demo implemented. Live voice/TTS, additional languages and adaptive questioning remain proposed. |

**Trust is a question to investigate, not a score to invent.** Low response, opt-out or abandonment could reflect connectivity, timing, language, relevance, device access, burden or trust. If Digital Green wants to study trust, it needs appropriately reviewed questions and field validation. Answer validity/completeness also does not establish whether an answer is truthful or agronomically correct.

## 3. Turn the Radar into an action system

An action card should contain:

| Field | What the reviewer sees |
|---|---|
| Finding and scope | Region, crop/advice context, observation dates and the measured pattern. |
| Evidence | Counts and denominators, source links, exclusions and missing information. |
| Recommended next step | One concrete action appropriate to the evidence. |
| Suggested owner | A role such as regional coordinator, MEL lead, language reviewer, channel operator or agricultural expert. Assignment requires an actual owner. |
| Reason and uncertainty | Why this action follows; distinguish observed facts from possible explanations. |
| Priority and review timing | Based on possible harm, evidence limitations and the agricultural action window—not simply the largest region. |
| Progress measure | What to measure after acting, with a baseline, time window and denominator. |
| Workflow and evidence version | Suggested → acknowledged/assigned → investigation/action recorded → follow-up checked → closed, deferred or reopened. Preserve the evidence snapshot behind each decision. |

The prototype currently has only suggested, acknowledged and demo-closed states. The fuller workflow above is a recommendation. Acknowledging or closing a card must not alter farmer answers or imply that a real farmer problem has been solved. New evidence should trigger fresh review.

### Example A: reported seed-access difficulty

**Implemented synthetic demonstration:** After the District A user answers “Yes” and “Could not obtain,” 10 of 22 accepted seed-access answers report difficulty. There are 30 due surveys. This is a respondent finding, not “45% of all farmers in the district.”

- **Next step:** Ask the regional field team to investigate local seed availability and affordability; obtain agricultural review if alternatives need consideration.
- **Suggested owner:** Regional programme coordinator, with a local field partner.
- **Why:** Several farmers explicitly report inability to obtain seed. The answers do not identify whether price, stock, distance or another issue caused it.
- **Check progress:** Record the investigation outcome, then track reported access difficulty and feedback coverage in a subsequent comparable, eligible survey window. Respect caps and opt-outs.

### Example B: a quiet district that needs attention

**Implemented synthetic baseline:** District B has only 4 accepted seed-access answers out of 30 due surveys, with 14 confirmed deliveries in finalized records. None of those four respondents reports a barrier. This does not show that District B is doing better.

- **Next step:** Review explicit delivery failures separately from delivered-but-unanswered surveys. Investigate channel reliability first where failure evidence supports that choice; investigate timing, language or usability where delivery is confirmed but participation is weak.
- **Suggested owner:** Channel/integration operator and MEL coordinator.
- **Check progress:** Delivery coverage and accepted-answer coverage, both with counts, denominators and observation windows. More responses demonstrate better coverage, not necessarily better agricultural outcomes.

### Example C: a question may be hard to answer

**Proposed extension; hypothetical example:** Among 30 farmers recorded as shown both questions, 18 give a valid answer to question one but only six to question two.

- **Next step:** Have a language/MEL reviewer inspect the second question, its options and channel rendering; test a clearer approved version on a comparable group.
- **Suggested owner:** Survey-design or language reviewer.
- **Check progress:** Accepted answers per farmer shown the applicable question, along with invalid-input rate and question version. Do not count an intentionally skipped branch as abandonment.
- **Uncertainty:** The gap does not by itself prove a translation defect, low literacy or distrust.

For a report of possible crop or animal harm, recommend prompt qualified human review of that report. Do not wait for a regional minimum sample, assert that the original advice caused the harm, or automatically prescribe a treatment.

## 4. Recommended order for the team

### First: one convincing, complete Radar-to-action demonstration

Preserve the working team application and add one simple Radar view containing:

1. Two clearly fictional, comparable districts and an explicit roster of surveys due.
2. One reported-barrier finding and one missing-feedback finding.
3. Counts/denominators and clickable source evidence for both.
4. One specific action card per finding, with a suggested owner, uncertainty and progress measure.
5. A farmer answer that visibly updates the underlying record and correct district totals.

This is the highest-value addition if presentation time is close. A simple table and two useful action cards are enough; a map is optional. Preserve all existing challenge requirements and scheduling protections while adding the view.

**Acceptance:** Replaying a response cannot inflate counts; failed delivery cannot become an agricultural barrier; missing answers remain visible; every factual card claim traces to evidence; recommendations differ appropriately for an access barrier and a delivery problem.

### Next: engagement and question-quality intelligence

Add a small funnel from due → attempted → confirmed delivered/shown → accepted answer → completed survey, with distinct decline, opt-out, invalid-input and unknown states. Delivery and display are different observations: do not infer that a question was seen merely because a message was delivered.

Show one question-level diagnostic and a concrete improvement suggestion. Compare language/channel/question versions only when their meanings and eligible populations are compatible. This demonstrates the communication-learning side of the product.

### Then: follow-up tracking and bounded AI assistance

Add owner assignment, investigation notes, evidence versions and before/after measures. If the team's existing Bedrock path is reliable and budgeted, let it draft an explanation/action from a bounded evidence bundle. Keep calculations and policy enforcement in code. Check both source references and whether the cited evidence actually supports each claim; reference existence alone is insufficient. Retain deterministic findings as a fallback.

### Later: pilot extensions

Time trends, broader crop/livestock and barrier categories, approved adaptive questions, voice/TTS, additional languages, geographic maps and production FarmerChat integration. Select these based on Digital Green's priorities rather than trying to include everything before judging.

## 5. Integration notes for developers

The local team README describes an existing writer/checker, scheduler simulation, response handling, API and Streamlit app. That is useful integration context, not a review of the teammates' latest deployed version. Agree on their current branch and interfaces before changing code.

**Recommended flow:** Existing team pipeline → adapter for validated insights/surveys/targets/responses → deterministic regional metrics → findings/evidence → action cards → team UI/review storage.

- Add a view or module to the team's application. Do not introduce a second scheduler, survey writer or competing source of truth just to reuse FarmerLoop code.
- Reuse official schemas and preserve farmer, insight, survey, handoff/flow and attempt identifiers. Keep Radar metadata and action records outside official contract objects unless the official schema permits them.
- Supply the complete eligible/due target roster at an explicit observation cutoff. Response records alone cannot identify farmers who were never reached. Clearly distinguish due, not-yet-due, opted-out, policy-blocked, pending and excluded records.
- Count surveys/farmers separately from attempts. A retry is not another farmer. An exact replay is idempotent; conflicting records need explicit handling rather than last-write-wins counting.
- **Do not feed arbitrary team surveys directly into the current analyzer.** It is tailored to a seed-access question, its options/follow-up tag and exact cohort signatures. It also expects source joins through handoffs and due targets. Build and test an adapter; generalize through explicit survey-objective/question-version mappings rather than assuming every `q2` means the same thing.
- Current `build_findings` deliberately requires `synthetic=True`. Preserve that guard for the hackathon. Real-data use needs a separate reviewed integration, not relabeling real records as synthetic.
- The interactive Radar consumes finalized canonical responses. Pending observations appear separately, and deliveries in its table are labeled as finalized-record counts. Do not overwrite a response repeatedly under one key as delivery and answers evolve; reduce lifecycle observations into a consistent analytics snapshot.
- Use matched crop/stage/topic/advice/question/time cohorts; show incompatible groups separately. A zero denominator means “no usable evidence,” not a 0% problem rate. Present demonstration thresholds as heuristics, not statistical significance or a calibrated trust/confidence score.
- Protect the team's chosen eligibility/timing policy. FarmerLoop's written-rule interpretation and the teammate README's golden-calibrated policy differ; do not silently mix them or transfer evaluation scores between implementations.

### Reusable reference map

Paths are relative to `po-aditya/team-41-digital-green-dc`.

| Reference | Useful contribution |
|---|---|
| `farmerloop/src/farmerloop/radar/analyze.py` | Validated joins, due denominators, deduplication/conflicts, cohort metrics and signals. |
| `farmerloop/src/farmerloop/radar/findings.py` | Deterministic findings, limitations, source chains and evidence lookup. |
| `farmerloop/src/farmerloop/radar/models.py` | Internal scenario envelope; not a general production API contract. |
| `farmerloop/src/farmerloop/radar/scenario.py` and `survey.py` | Clearly synthetic scenarios and a narrow bilingual seed-access survey. |
| `farmerloop/src/farmerloop/interactive_demo.py` | Connecting scheduler state, user taps, finalized responses, Radar and evidence-specific demo reviews. |
| `farmerloop/streamlit_app.py` | Temporary interaction/evidence walkthrough, not a required UI design. |
| `farmerloop/src/farmerloop/respond.py` | Deriving structured outcomes from observations using official definitions. |
| `farmerloop/src/farmerloop/scheduler.py` | Persistent caps, opt-outs, attempt reservations and restart behavior; selectively reuse safeguards/tests if needed. |
| `farmerloop/tests/test_radar_*.py` | Detection, evidence, denominator, context, duplicate/conflict and counterexample tests. |
| `farmerloop/tests/test_interactive_demo.py`, `test_streamlit_app.py`, `test_scheduler.py` | Interactive journeys, restart/reset, opt-outs, timing and replay checks. |

## 6. Evidence, limits and source availability

- **Repository:** https://github.com/po-aditya/team-41-digital-green-dc
- **FarmerLoop branch:** `feature/jeremiah-farmerloop`.
- **Last committed/pushed code baseline before this documentation update:** `a7d6265b9fdd8c9f2d5e789a750b5b9d66e6423e`.
- **Important:** This handoff is published separately from the interactive Checkpoint C implementation. That implementation's code/docs remain local, uncommitted additions at handoff time. Fetching the baseline or this documentation update does not include them. Obtain the current source package or arrange an explicit commit/share step before integrating those files.
- **Existing source package:** `farmerloop-demo-checkpoint-3.zip`, with `VERSION.txt`, `SOURCE-SHA256.json`, source/tests and the participant pack. It is a source snapshot, not a Git checkout. This new suggestion handoff is a separate document.
- **Previously verified current-build results:** 543 passing FarmerLoop tests, including 27 interactive-service tests and three Streamlit journeys; existing offline demos passed; a Chromium interaction demonstrated the 9 → 10 barrier update. This documentation task does not constitute a new test run or verification of the final combined product.
- The current feature works with synthetic evidence. It does not establish regional prevalence, better yields, improved trust or real-world impact. The official response examples are conformance fixtures, not independent field observations suitable for regional claims.
- Existing schema/lexical screens are not independent semantic or agricultural certification. No new live AWS Radar investigation, real messaging or real FarmerChat integration is claimed.

The original [ideas/research handoff](REGIONAL_LEARNING_RADAR_IDEAS.md) preserves the broader brainstorming, but its implementation-status section is historical. See [Radar checkpoints](RADAR_CHECKPOINTS.md), [scheduler notes](SCHEDULER_CHECKPOINT.md), [quality results](SURVEY_QUALITY.md), and [policy decisions](DECISIONS.md) for supporting context. The latest Checkpoint C documentation, including `farmerloop/docs/INTERACTIVE_DEMO.md`, is in the source package and has not yet been pushed; older linked documents may therefore describe the interactive integration as future work.

## 7. How to make this compelling to judges

**Demo sequence:** Show advice → a short relevant survey → a farmer reporting difficulty → a regional barrier finding → a second district with little feedback → different recommended actions → source evidence. Show that a new answer changes the counts. End with the next pilot step and who would act on the findings.

The memorable moment is: **“This district looks like it has fewer problems, but we haven't heard from enough of its farmers to conclude that.”** Then show what Digital Green should do about that gap.

| Strength | Concrete evidence to show |
|---|---|
| Useful differentiation | Agricultural barriers and missing perspectives analyzed together, followed by different actions. |
| Technical substance | A real answer updates validated records and computed results; source evidence resolves. |
| Responsible interpretation | Honest denominators, context matching, missingness and no invented trust/causality claims. |
| Operational usefulness | A named type of owner, clear next step and progress measure on each card. |
| AWS contribution | Demonstrate the team's actually verified AWS path; if added, distinguish Bedrock-assisted investigation from deterministic analytics and offline fallback. |
| Potential to continue after the event | A teammate can run it; a Digital Green owner can review and act; a small pilot has defined measures. |

These are presentation strengths, not verified official scoring categories or weights. Recheck the current event rubric and required submission materials before finalizing the pitch. The participant pack requires contextual surveys, scheduling and simulated response handling; Radar/action cards extend that baseline. Real channel delivery is explicitly outside the supplied pack's scope.

### Suggested 30–60 second STAR pitch

- **Situation:** Giving farmers advice is only half the job. Digital Green also needs to know what happened afterward—and whose experience it never heard about.
- **Task:** Turn farmer feedback into regional understanding and practical next steps, while making overlooked communities visible.
- **Action:** Our Regional Learning Radar connects shared agricultural barriers, participation patterns and feedback gaps to supporting evidence and human-review recommendations. A seed-access problem and a delivery problem should lead to different actions.
- **Result:** Our synthetic prototype demonstrates regional barriers and missing feedback. The combined product aims to close the loop from advice to feedback, regional understanding and action. Describe broader engagement analytics and richer action cards as proposed until they work in the final build.

## 8. Ownership and the first team decision

**Recommended first decision:** Adopt the narrow Radar + blind-spot + evidence + action-card slice in the main application. Assign one integration owner, one MEL/action-content reviewer and one demo/test owner; roles may overlap on a small team. Confirm which pieces already exist before adding them.

For continued use, Digital Green should validate which findings matter, who owns follow-up, appropriate cohort sizes/thresholds, language quality, access permissions and retention. Measure useful reviewed actions, coverage and staff turnaround—not just survey volume. Aggregate views and controlled evidence access are important when moving beyond fictional farmers, especially for small geographic groups.

The aim is a stronger shared product: **the team's complete delivery workflow, enhanced by FarmerLoop's regional learning and actionable follow-up ideas.** No feature list can guarantee a competition win; a focused, credible demonstration of this loop gives the team a clearer contribution to defend.
