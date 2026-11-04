# Golden-set evaluation

Cases: 150

## Eligibility (survey / no survey)

| | golden: survey | golden: no survey |
|---|---|---|
| ours: survey | TP 93 | FP 0 |
| ours: no survey | FN 2 | TN 55 |

Precision 1.0, recall 0.9789, accuracy 0.9867, F1 0.9894. No-survey reason-code agreement 55/55.

## Agreement by golden rule

| rule | cases | agree |
|---|---|---|
| R1 | 14 | 14 |
| R2 | 6 | 6 |
| R3 | 12 | 12 |
| R4 | 10 | 10 |
| R5 | 10 | 10 |
| R6 | 2 | 2 |
| R7 | 1 | 1 |
| R8 | 95 | 93 |

## Mismatches

- **I-006279**: golden R8/survey vs ours R7/crop_already_harvested. rules.json timing (start not before the action window ends) puts the first send date after this crop's calendar end; the golden formula (no action-window clamp) starts earlier and keeps the survey. Contract disagreement, not a code defect.
- **I-006836**: golden R8/survey vs ours R6/window_truncated_by_season_end. rules.json requires a window at least min_width_days wide AND nothing after 31 March; both cannot hold for this insight, so it is held back rather than sent with a truncated window. The golden set accepts the truncated (even zero-width) window. Conservative decision pending Digital Green's ruling.

## Timing (rules.json formula vs golden windows)

Of 93 surveys both sides agree on: same start date 18, same end date 37, both 14, overlapping windows 86, ours inside golden 22.

## Channel

First channel matches golden: 93/93.

## Format (en-IN)

Generated 93 (failures 0); survey schema valid 93; hand-off schema valid 93; 1–3 items 93; same item count as golden 67.

## Relevance proxy

Lexical overlap with golden items: mean 0.5397, min 0.1739; surveys naming the crop/animal 93/93. Jaccard over content words of prompts+labels vs golden item texts+options (proxy only).

## Notes

- Eligibility uses rules.json + the content-based junk signature; the golden labels are never read by the decision code.
- Timing is computed with the rules.json formula (which reproduces the pack's worked scenarios). The golden set uses a different formula (09:00 start, no action-window clamp), so date agreement is reported separately from overlap.
- Relevance is a lexical proxy (token overlap with the golden item texts), not a judgement of language quality.
