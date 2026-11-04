```json
{
  "features": [
    {
      "id": "failed_advice",
      "title": "Failed-Advice Safety Loop (Proposed Extension)",
      "mermaid": "flowchart LR\n  A[\"Negative tap: did not work or crop damaged\"] --> B[\"Response linked to survey and source insight\"]\n  B --> C[\"Rule creates simulated follow-up case\"]\n  C --> D[\"Human review queue\"]\n  D --> E[\"Case status shown in farmer view\"]\n  E --> F[\"Fixed template only, never new advice\"]",
      "inputs": [
        "Response JSON (survey_id, farmer_id, answers[].option_id, answered_at)",
        "Survey JSON with source_insight_ids and item options",
        "Insight record (crop, topic, advice_summary, resolution_type)",
        "Proposed negative-outcome tag map (option_id to outcome code, such as not_improved or crop_damaged)"
      ],
      "steps": [
        "Tag negative outcome option IDs deterministically at generation time; do not let Bedrock decide which answers count as failure",
        "On POST /responses, validate with Pydantic, write the response linked to the survey and insight, and have a rule create one case {case_id, status: open, source_insight_ids}",
        "Add a reviewer view listing open cases with insight context; the reviewer sets status (reviewed, referred, closed). No LLM call on this path",
        "Render the case status to the farmer from fixed, pre-approved templates, and add a test asserting the farmer-facing text contains no agronomic instructions"
      ],
      "minimum_demo": "A synthetic Bihar mustard farmer taps 'Sprayed, aphids not reduced'. A linked case appears in the reviewer list. The reviewer marks it 'referred', and the simulated phone shows a fixed status message such as 'Your report was sent to an expert for review'.",
      "dependencies": [
        "Baseline: Survey JSON contract and simulated app",
        "Exploratory: response write-back",
        "Agreement on negative-outcome option tags",
        "Optional: DynamoDB table for cases (in-memory or SQLite is acceptable for the demo)"
      ],
      "acceptance_check": "Every negative-tagged answer creates exactly one case linked to its source insight. Non-negative answers create none. All farmer-visible text comes from fixed templates. The path makes zero Bedrock calls. A safety check finds no new advice.",
      "source_scope": "Exploratory. The Vision lists Negative-outcome follow-up and Response write-back as Exploratory and Journey 3 as a stretch. The Safety Tenet requires failed or damaged outcomes to be routed for follow-up rather than only recorded. The human-review queue and visible case status are authored proposals that simulate the FarmerChat advice path, which is unavailable at the hackathon.",
      "one_day_tradeoff": "Fully deterministic, so roughly 2 to 3 hours, and it gives a strong trust and safety story. It does not deliver real remediation, and it competes for time with eval iteration, so build it only after the baseline pipeline runs."
    },
    {
      "id": "season_timeline",
      "title": "Season Timeline Replay (Proposed View over Baseline Scheduler)",
      "mermaid": "flowchart LR\n  A[\"Insight: action window and crop stage\"] --> B[\"Deterministic send window rule\"]\n  B --> C[\"Simulated clock Nov to Mar\"]\n  C --> D[\"Frequency cap and grouping\"]\n  D --> E[\"Due survey to broadcaster stub\"]\n  E --> F[\"Timeline of scheduled, deferred, delivered\"]",
      "inputs": [
        "Insight fields: created_at, resolution_type, action_window_days, crop, crop_stage",
        "Crop calendar for Bihar rabi crops",
        "Validated survey JSON that passed self-eval",
        "Cap configuration (for example, at most 1 survey per farmer per 7 days)"
      ],
      "steps": [
        "Compute send_window with rules keyed on resolution_type, action_window_days and the crop calendar stage, then record a reason string",
        "Implement a shared simulated clock with advance and jump endpoints, plus a manual trigger for each scheduled step",
        "Apply a per-farmer rolling cap. Defer overflow surveys with a reason code, or group overlapping windows (grouping is a proposed rule)",
        "Render a per-farmer season timeline showing scheduled, deferred, delivered and skipped items with their reasons"
      ],
      "minimum_demo": "Scrub the simulated clock from December to February for 3 synthetic farmers. Surveys appear only inside their windows, a capped farmer shows one deferred survey with a reason, and the timeliness score from the eval harness is displayed alongside.",
      "dependencies": [
        "Must Have: survey scheduler with frequency cap",
        "Should Have: broadcaster stub and simulated app",
        "Crop calendar data (confirm source)",
        "Must Have: evaluation harness timeliness check"
      ],
      "acceptance_check": "On the simulated clock, no survey is delivered outside not_before/not_after. No farmer exceeds the cap in any rolling window. Every deferral or skip has a reason code. Deterministic timeliness checks pass on the golden set.",
      "source_scope": "Mostly Must and Should baseline. The scheduler, frequency cap and send windows are Must Have, and the broadcaster stub and simulated clock are Should Have. Multi-insight grouping is a Vision open question, and the replay timeline view is an authored exploratory presentation layer.",
      "one_day_tradeoff": "Lowest marginal cost, because the scheduler and clock are required anyway, and it makes timeliness visible to judges. On its own it is weak as a differentiator. Skip grouping if the cap and deferral logic are not stable by mid-afternoon."
    },
    {
      "id": "adaptive_survey",
      "title": "Adaptive Adoption Survey Branching (Proposed Extension, Schema Must Be Agreed)",
      "mermaid": "flowchart LR\n  A[\"Adoption tap: did you try it\"] --> B{\"Tried?\"}\n  B --> C[\"Yes: fixed outcome options\"]\n  B --> D[\"No: fixed barrier options\"]\n  C --> E[\"Linked response record\"]\n  D --> E",
      "inputs": [
        "Insight record and resolution_type",
        "Fixed outcome option set (improved, no change, worse, too early to tell)",
        "Fixed barrier option set (product unavailable, too costly, weather, not needed, other)",
        "Proposed survey item extension such as show_if {item_id, option_ids}, pending Digital Green agreement"
      ],
      "steps": [
        "Define the branching skeleton deterministically per resolution_type. Bedrock writes only the adoption prompt grounded in advice_summary, and option sets stay fixed",
        "Add an optional show_if field to the item schema, and keep a flat fallback where all items render, so the baseline contract remains valid",
        "Make the simulated app reveal the outcome or barrier item based on the first tap, and store answers with the path taken",
        "Extend self-eval to check that all options come from the fixed sets, the path is at most 3 taps, and no item contains advice"
      ],
      "minimum_demo": "One wheat irrigation insight on the simulated phone. Tapping 'Yes' shows outcome options, and tapping 'No' shows barrier options. Both paths write linked responses, and the same survey also renders in flat fallback mode.",
      "dependencies": [
        "Must Have: survey JSON contract and self-evaluation step",
        "Should Have: simulated app",
        "Exploratory: response write-back",
        "Digital Green agreement on show_if extension (fallback if not agreed)"
      ],
      "acceptance_check": "Surveys validate with and without show_if. Every option ID belongs to the fixed sets. No path exceeds 3 taps. Each response record carries the survey_id, source_insight_ids and branch path.",
      "source_scope": "Exploratory, built on Must Have. Tap-based fixed-option items and the survey contract are Must Have. Conditional branching is an authored proposal that changes the agent-to-UI contract, which the Vision flags as a High-impact risk unless agreed.",
      "one_day_tradeoff": "It yields richer MEL data, with barriers and outcomes, at the same tap cost. However, a contract change can conflict with golden-dataset format scoring. Build it only if the extension is agreed early, otherwise ship the flat fallback."
    },
    {
      "id": "bilingual_views",
      "title": "Bilingual Farmer and MEL Views (Proposed Extension over Hindi Should Have)",
      "mermaid": "flowchart LR\n  A[\"Survey with stable item and option IDs\"] --> B[\"Bedrock renders hi-IN labels\"]\n  A --> C[\"English en-IN labels\"]\n  B --> D[\"Hindi farmer tap view\"]\n  D --> E[\"Responses stored by option ID\"]\n  C --> F[\"English MEL view\"]\n  E --> F",
      "inputs": [
        "Canonical en-IN survey JSON with stable item_id and option_id values",
        "Target language BCP 47 code (hi-IN)",
        "Response JSON keyed by option IDs",
        "Hindi reviewer checklist (participant or Digital Green review)"
      ],
      "steps": [
        "Generate the canonical en-IN survey first, then request a hi-IN variant from Bedrock that must reuse identical item and option IDs and change only labels",
        "Keep the contract unchanged by emitting two survey objects that share IDs and differ in language, rather than adding new multi-label fields",
        "Add an equivalence check: deterministic ID-set match plus an LLM-judge or back-translation comparison per option, with low scores flagged for Hindi review",
        "Render the Hindi tap view for the farmer and the English view for MEL staff. Both read the same response records through option IDs"
      ],
      "minimum_demo": "The same mustard aphid survey appears side by side, in Hindi on the simulated phone and in English in the MEL view. One Hindi tap appears in the English view as the matching option. Voice is not shown, since it is a stretch.",
      "dependencies": [
        "Must Have: survey JSON contract",
        "Should Have: Hindi surveys via hi-IN parameter",
        "Bedrock model with acceptable Hindi quality (confirm availability)",
        "Hindi-speaking reviewer for spot checks"
      ],
      "acceptance_check": "The hi-IN and en-IN variants have identical item and option ID sets. The equivalence check passes or is flagged for every option. A Hindi answer maps to the correct English label in the MEL view. No code change is needed to switch language.",
      "source_scope": "Should Have, plus an exploratory view. Hindi surveys are Should Have, and the MVP criterion requires hi-IN output from the same agent. The paired dual-view and equivalence check are authored proposals. Voice delivery is Exploratory (Alternative channels) and is treated as a stretch only.",
      "one_day_tradeoff": "It largely reuses Should Have work and shows the 'language is a parameter' principle well. Automated Hindi quality is hard to verify in a day, so rely on ID-level guarantees and a small reviewed sample. Do not attempt voice."
    },
    {
      "id": "mel_insights",
      "title": "MEL Pattern Insights Dashboard (Proposed Extension, Descriptive Only)",
      "mermaid": "flowchart LR\n  A[\"Linked self-reported responses\"] --> B[\"Aggregate by crop, topic, resolution type\"]\n  B --> C[\"Adoption, barrier, failure rates\"]\n  C --> D[\"Drilldown to survey and insight\"]\n  D --> E[\"Follow-up priorities for MEL team\"]\n  E --> F[\"Descriptive, not causal proof\"]",
      "inputs": [
        "Response records linked to survey_id and source_insight_ids",
        "Insight metadata (crop, topic, district, resolution_type)",
        "Clearly labeled simulated response set, since no real answers exist",
        "Optional: barrier and outcome codes from adaptive_survey and case records from failed_advice"
      ],
      "steps": [
        "Generate a synthetic response set with documented distributions, and label it as simulated in the data and the UI",
        "Compute adoption, barrier and failure rates deterministically with Python grouping, showing counts and denominators beside every rate",
        "Add drilldown from any aggregate cell to the underlying surveys, insights and cases",
        "Optionally use Bedrock to write a short narrative summary grounded only in the computed numbers, with a fixed non-causal disclaimer"
      ],
      "minimum_demo": "A table of mustard pest advice shows 62 percent self-reported adoption, with 'product unavailable' as the top barrier in one district. Clicking through reaches individual linked responses and insights, and a banner states that figures are simulated and descriptive, not RCT evidence.",
      "dependencies": [
        "Exploratory: response write-back",
        "Simulated response generator",
        "Optional: adaptive_survey barrier codes and failed_advice cases",
        "Optional: S3 for run artifacts or DynamoDB for responses"
      ],
      "acceptance_check": "Every displayed rate shows its numerator and denominator and reconciles with raw records. Drilldown reaches source insights. Any narrative cites only computed figures. The UI and narrative contain no causal or RCT-replacement claims.",
      "source_scope": "Exploratory. Response write-back is Exploratory, and turning answers into adoption and outcome measures is a stretch open question in the Vision. Replacing RCTs is explicitly out of scope, and RCTs remain the verifier.",
      "one_day_tradeoff": "It speaks directly to the MEL team's business need. However, it rests entirely on simulated responses, which can look like fabricated evidence if not labeled clearly. Keep it as a thin read-only view, or cut it."
    }
  ],
  "recommended_combination": "Secure the baseline first: ingestion, Bedrock generation, self-eval, the eval harness with one improvement iteration, and the scheduler with frequency cap. Then add season_timeline, which costs little on top of the required scheduler and clock and makes timeliness visible. Add failed_advice as the differentiator: it is deterministic, low-risk and maps directly to the Safety Tenet. Add adaptive_survey only if Digital Green agrees the show_if extension by midday, otherwise keep flat surveys. Limit bilingual_views to the Should Have hi-IN output, with an ID-equivalence check. Treat mel_insights as a thin, clearly labeled stretch view if time remains.",
  "caveat": "These five workflows, diagrams and outlines are authored proposals, not content from the Vision or Technical documents, and no feature has been selected or authorized for implementation. Evals and Must Have requirements are the baseline, not the differentiator, and must work first. All data and responses are synthetic and delivery is simulated. Schema extensions (show_if, negative-outcome tags) need Digital Green agreement. Time estimates are rough. Nothing here supports causal or RCT-replacement claims. DynamoDB and S3 are optional, and no other AWS services are assumed."
}
```
