# Teammate handoff: useful additions for the FarmerChat MEL demo

This is a research and ideas brief, not a new implementation specification. It incorporates the Digital Green challenge documents, the supplied synthetic participant pack, a read-only review of DG_Open, current team-repository documentation, and research into past hackathon winners. Recommendations are optional and ordered by likely value for the remaining build time.

## Start here

**Recommended pitch:** “We respect the farmer’s time: ask only useful questions, at a useful time, and make answering accessible.”

The team already has substantial implementation. The [current README](../README.md) describes insight ingestion, eligibility decisions, generation, validation, scheduling, simulated answers, follow-up queues, English/Hindi templates, an offline provider, and a guarded Bedrock provider. There are already [Terraform deployment files](../Terraform/README.md), [validation results](CONSOLIDATION_VALIDATION.md), and a [security review](CONSOLIDATION_SECURITY.md). Build on those rather than creating a second pipeline.

The most valuable remaining work appears to be **better evidence of question quality, an accessible farmer interaction, and a convincing repeatable AWS demo**. This brief checked those reports; it did not rerun their tests, audit every branch, deploy infrastructure, or call a model.

## Three ranked improvements

Effort estimates are relative, not promises. Existing UI and deployment work may change them.

| Rank | Improvement | Usefulness | Incremental effort |
|---|---|---|---|
| 1 | Make the four survey checks visible and evaluate their quality | Very high; directly answers the challenge and team lead’s questions | Low–medium for a focused set of cases and a compact UI |
| 2 | One polished Hindi voice interaction with answer confirmation | High; demonstrates accessibility beyond translated text | Medium–high; narrow scope to one tested interaction |
| 3 | Package repeatability, security evidence, and an AWS-hosted demo | High for technical credibility and teammate handoff | Low for an evidence page; medium–high for deployment |

### 1. Turn the four checks into an inspectable decision and a measured result

For each demonstrated insight, show a small reviewer panel:

- **Does this warrant a survey?** Identify the action or outcome that can actually be checked. Show a legitimate no-survey example.
- **Is this the right question?** Connect each question to the specific advice and what the farmer could reasonably observe.
- **How relevant is it?** Check that it measures the action, outcome, or barrier, rather than generic satisfaction. Preserve source insight IDs.
- **Is this the right time?** Explain the action window, crop context, allowed send hours, and frequency-cap decision.

Use concise reason codes and short explanations, not hidden reasoning or model chain-of-thought. Keep diagnostics in a separate report: strict participant schemas must remain unchanged.

**Why this adds value now:** the existing [validation report](CONSOLIDATION_VALIDATION.md) reports 148/150 eligibility decisions correct, but explicitly says this does not establish semantic relevance or Hindi fluency. Only 14/93 generated windows match both golden dates; 86/93 overlap. These are reported results from that review, not new measurements here. The mismatch is already discussed in [contract questions](CONTRACT_QUESTIONS.md), so present the policy choice honestly rather than claiming perfect timing.

**Small implementation:** add a reviewer view over existing decisions, surveys, handoffs, and audit data. Select a compact, fixed set covering direct action, wait-and-monitor, no survey, expert escalation, frequency suppression, and season boundaries. Compare an initial and improved question/prompt on the same cases.

**Evaluation evidence:** separate eligibility, schema validity, question relevance, answerability, timing compliance, and language quality. Report the denominator and sample size. Use a human reviewer for Hindi and agricultural meaning where available; an LLM judge is supporting evidence, not ground truth. Keep a holdout subset separate from examples used to tune prompts. Record model/prompt version and, for authorized model runs, latency, tokens, and cost.

A proposed question-quality rubric can score each dimension from 0–2: grounded in the advice, measures something actionable, answerable at the scheduled time, and understandable without adding new advice. Label it as a proposed rubric. Do not publish invented scores.

### 2. Demonstrate voice with confirmation, not just text-to-speech

Aim for one short Hindi interaction rather than many untested languages:

1. The farmer can tap a speaker button to hear the question and choices.
2. They answer by tap or a short spoken response.
3. The UI presents the interpreted choice in the same language and asks them to confirm or correct it.
4. Only the confirmed choice is stored as the structured answer.

For example, a synthetic irrigation follow-up can ask whether the advised action happened. “No” should allow a practical barrier such as lack of water, where supported by the chosen survey and answer catalogue. Avoid introducing new agronomic instructions.

Map speech to the existing option values or scale range. Preserve question IDs, survey identity, language, and provenance. An unclear recording should lead to replay or tap selection, not an invented answer. Optional free speech can enrich a review queue, but it must not silently alter the canonical structured response.

**Connectivity:** save progress locally for the synthetic demo, allow retry, and use response idempotency to avoid duplicate submissions. Cached text/audio can help replay. Clearly distinguish this from offline speech recognition: cloud transcription still needs connectivity.

**Current gap:** the README says Hindi templates have not had Hindi-speaker review. A scheduler channel called “voice” is not evidence of working speech input/output. Confirm what the selected UI already supports before adding an adapter.

Amazon Polly and Transcribe are candidate AWS services; verify the selected language, engine, region, and account support before implementation. [Polly bilingual voices](https://docs.aws.amazon.com/polly/latest/dg/bilingual-voices.html) and [Transcribe supported languages](https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html) provide the service details. No speech calls were made for this brief. A prerecorded fallback is acceptable for demo resilience if clearly identified as prerecorded.

### 3. Present a small, reproducible evidence package

Reuse the existing deployment and test work. The current README says infrastructure **has not been deployed**. Infrastructure files alone do not demonstrate a running AWS application.

A useful evidence page would contain:

- The selected application/runtime and commit, with a single documented setup/demo path.
- A fixed synthetic scenario set and simulated clock, so judges can repeat the sequence without waiting days.
- The actual AWS deployment URL and architecture once deployed, plus limitations and teardown instructions.
- Evaluation results with sample sizes and failures.
- Security checks with tool/version, scope, date, and unresolved findings.
- Clear separation of live Bedrock results from deterministic offline/template runs.

**Security additions worth considering:** secret scanning, dependency vulnerability scanning, static analysis, and Terraform/container configuration checks. Run these through existing CI tooling where practical. Also demonstrate rejection of invalid responses, wrong survey/farmer associations, duplicate submissions, and unauthorized operator requests using existing tests.

The current [security report](CONSOLIDATION_SECURITY.md) already documents targeted source/security tests and pattern scans. It explicitly says no online dependency vulnerability database audit or production assessment was performed. Fill that evidence gap if time permits; do not describe the existing review as a clean comprehensive vulnerability scan. A passing scan is scoped evidence, not proof of security.

Use existing paid-inference controls and an explicit AWS budget. The runtime’s model budget does not cover every AWS service, other prototypes, or account activity. This handoff does not authorize spending or deployment.

## A short judging demo

1. **Advice → relevant survey:** show a synthetic insight, its source link/ID, one or two questions, and why those questions fit.
2. **Restraint:** show a generic-information insight deliberately receiving no survey.
3. **Timing:** advance the simulated clock; show one survey deferred because it is too early or the farmer’s weekly allowance is used.
4. **Accessibility:** play one Hindi question, accept a short answer, and confirm the interpretation before saving.
5. **Learning:** show a negative outcome reaching the existing follow-up queue. This is a simulated handoff, not an expert actually contacted.
6. **Evidence:** finish with measured evaluation results, AWS deployment status, and reproducibility/security evidence.

If time is tight, prioritize the first three and one honest evaluation comparison. Add voice when the core interaction is reliable. Do not trade a complete working flow for a long list of unfinished features.

The supplied DC event guide describes four equally weighted areas: technological implementation, design, potential impact, and quality of idea. Map the demo to all four. The Digital Green technical brief emphasizes evaluated survey quality; elaborate infrastructure is secondary. These are different lenses, not competing requirements.

## What previous winners suggest

These examples establish what teams built and achieved. They do not prove which feature caused a win, and none establishes that security scans alone improve placement.

| Example | Relevant evidence | Practical lesson for this project |
|---|---|---|
| Bookmark Reading, London Breaking Barriers 2026 winner | The charity describes its winning personalized reading-support project. [Primary account](https://www.bookmarkreading.org/news/aws-breaking-barriers-2026-bookmark-win) | Center a recognizable person’s need and show the experience working. |
| LLMIX, first place in the 2025 virtual Breaking Barriers event | AWS lists the winner; the team describes local/offline access through a portable hotspot and lightweight interface. [AWS results](https://aws.amazon.com/telecom/breaking-barriers/) · [Project](https://devpost.com/software/llmix) | Limited connectivity belongs in the demonstrated user journey. Reuse the principle, not its hardware stack. |
| Buzzle, second place in the same event | A screenless voice experience with AWS services and a browser-based demo. [Project](https://devpost.com/software/buzzle) | Make the interaction easy to try; prepare a fallback. Its cloud-connected voice design is not evidence of fully offline speech. |
| Agri-able, third place in AWS ASDI 2022 | AWS describes crop suitability informed by environmental data. [AWS account](https://aws.amazon.com/blogs/publicsector/announcing-winners-2022-amazon-sustainability-data-initiative-asdi-global-hackathon/) | Connect context to a specific farmer decision rather than presenting a generic chatbot. |

The synthesis is our recommendation: a small, accessible, demonstrably useful flow with credible measurements is a stronger focus than feature count. Survey answers can reveal reported adoption, outcomes, and barriers; they do not by themselves prove causal agricultural impact.

## Integration reminders and source map

**Use the existing insight-extractor output as the boundary.** The challenge’s synthetic insight records already provide the context for the MEL agent. Do not insert survey generation inside FarmerChat’s answer-writing path or connect to production.

Conceptual flow:

```text
synthetic extracted insight + farmer profile + crop calendar
  → eligibility decision
  → grounded survey + validation
  → schedule and frequency checks
  → simulated delivery
  → structured confirmed answer
  → follow-up queue and evaluation
```

The original DG_Open code is useful background, not the current team implementation or a complete description of current production FarmerChat. Review was pinned to commit `5064d65700e03d413cd283dbafc12386f6b92f75`.

| Original code finding | Exact source |
|---|---|
| Django API routing; text-answer entry point | [api/urls.py:7](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/api/urls.py#L7), [api/views.py:47](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/api/views.py#L47) |
| Query processing and RAG orchestration | [api/utils.py:132](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/api/utils.py#L132), [execute_rag.py:19](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/rag_service/execute_rag.py#L19) |
| Suggested conversational follow-ups, not delayed MEL surveys | [common/utils.py:223](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/common/utils.py#L223) |
| Message/resource feedback fields and follow-up-question model | [database/models.py:202](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/database/models.py#L202), [models.py:263](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/database/models.py#L263), [models.py:318](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/database/models.py#L318) |
| Speech synthesis, transcription, voice-query endpoints | [api/views.py:100](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/api/views.py#L100), [views.py:158](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/api/views.py#L158), [views.py:258](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmer-chat/api/views.py#L258) |
| Farmstack scheduled dataset refresh, not farmer survey scheduling | [core/settings.py:462](https://github.com/digitalgreenorg/DG_Open/blob/5064d65700e03d413cd283dbafc12386f6b92f75/farmstack-backend/core/settings.py#L462) |

The reviewed open-source version has feedback and language components, but no complete advice-specific, delayed MEL workflow was identified. It uses older Python and non-Bedrock providers; copying its runtime would not satisfy the challenge’s Python 3.12+/Bedrock requirement automatically. The team’s current implementation already addresses that separation.

## Contracts and scope that should remain intact

The [participant pack](../data/participant-pack/) is the practical starting point: schemas, worked scenarios, rules, synthetic farmers/insights, golden examples, and simulated response outcomes. The [vision and technical briefs](Digital%20Green%20Foundation/) explain the intended scope.

- Keep surveys to 1–3 short items. Preserve the supplied question types, option values, source insight IDs, and response contract.
- The strict survey schema allows only its defined fields. Put additional quality scores and decision explanations in reviewer reports or separate API data.
- Use the supplied action windows, send hours, season boundaries, and cross-channel frequency rules. The baseline is one survey per seven days with a high-priority exemption; document any justified policy change.
- Keep the clock injectable and delivery simulated. Availability, opt-out, retry, and expiry behavior should be explicit rather than inferred from a model’s prose.
- The no-survey schema only accepts two external reason codes, while the materials contain richer internal reasons. Existing [contract questions](CONTRACT_QUESTIONS.md) record this and timing disagreements; do not silently change schemas to make scores look better.
- English end-to-end is the baseline; reviewed Hindi is valuable. More languages and a general voice platform can wait.
- All farmers, advice, responses, and channel activity remain synthetic. No production FarmerChat integration, real messaging, or new agricultural advice is needed.
- Keep the selected runtime clear: the repository preserves multiple prototypes whose APIs, stores, policies, and evaluation scores are not interchangeable.

## Suggested next decision

Choose the existing runtime and UI for the demo. Then implement **one small quality-evidence view**, rehearse the core synthetic scenario, and add **one reviewed Hindi voice path** if time allows. Reuse deployment/security assets and publish only results actually obtained.

No application code, infrastructure, or participant data was changed to prepare this brief. No new security scans, test runs, paid inference, or deployment were performed.
