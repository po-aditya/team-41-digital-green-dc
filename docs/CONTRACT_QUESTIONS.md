# Open contract questions for Digital Green

These are places where the supplied materials disagree with each other, or
leave a safety-relevant choice open. For each one the implementation takes the
conservative option and records why. None of them is a code defect; all of them
need a ruling before a pilot.

## 1. Send-window formula: `rules.json` vs the golden set

`rules.json` (and the five worked scenarios, which it reproduces exactly) says:
days count from the insight's calendar day in IST, the window opens 07:00 and
closes 19:00, never on the advice day, never before the action window ends, at
least `min_width_days` (2) wide, nothing after 31 March.

The golden set's `expected.send_window` follows a different formula: 09:00 start,
no action-window clamp, `seasonal` as days 30–45, and for `same_day` a 4-hour
window starting 4 hours after `created_at` (or 09:00–13:00 next day after 17:00).

Measured on the 93 golden surveys both sides accept: same start date 18, same end
date 37, both 14, overlapping 86, ours inside golden 22. **We implement
`rules.json`.** Which formula is authoritative?

Also: the golden `same_day` windows count elapsed hours; `rules.json` counts
calendar days. We use calendar days ("Days count from the day of the insight").

## 2. Two-day minimum width vs 31 March season end

Both rules cannot hold for insights created from ~16 March whose window would end
in April. Affected in the dataset: **36 insights** (I-006250, I-006276, I-006289,
I-006494, I-006547, I-006594, I-006603, I-006609, I-006633, I-006641, I-006646,
I-006655, I-006663, I-006677, I-006687, I-006689, I-006690, I-006710, I-006716,
I-006720, I-006722, I-006731, I-006732, I-006737, I-006750, I-006755, I-006767,
I-006786, I-006806, I-006812, I-006820, I-006824, I-006835, I-006836, I-006849,
I-006887). Golden case **I-006836** expects a survey with a zero-width window
(31 March 09:00–19:00).

**We hold these back** (`window_truncated_by_season_end`, external code
`generic_information`) rather than send a window shorter than the minimum. This is
a **provisional conservative policy**, not a reading that one rule outranks the other:
it lowers golden agreement by one case (149/150 → 148/150) and should not be read as
an accuracy change in either direction until Digital Green rules.
Alternatives: (a) send a truncated window (golden behaviour); (b) extend past
31 March; (c) drop the minimum width in the last week. Which one?

## 3. Crop-calendar end boundary (R7)

`crop_already_harvested` fires when the window's **first** day is after the crop's
last calendar date. Case **I-006279** (cauliflower, calendar ends 20 March):
`rules.json` timing starts 21 March → suppressed; the golden formula starts
18 March → survey. Should the boundary be "window starts after crop end",
"window ends after crop end", or "created_at after crop end"? Should a start
exactly on the last calendar day count?

## 4. External `no_survey` reason codes

`no_survey.schema.json` permits only `generic_information` and
`needs_more_context`. Internal reasons are richer (junk, critical→human, no check
needed, after season, truncated, harvested). Mapping used: R2 and R4 →
`needs_more_context`; everything else → `generic_information`, with the internal
reason in the free-text `reason`. Should the schema grow these codes?

## 5. Critical records that look like junk (H7)

A record with `severity: critical` and `decision_episode_type: casual` (or other
junk signals) is routed to the human queue, not binned. Is a human call the
intended handling of contradictory critical records?

## 6. Semantically empty but schema-valid records

Records whose `query_summary` / `advice_summary` are unreadable or identical are
treated as junk. The readability floor is script-neutral: it needs at least 8
characters, letters in *any* script (Devanagari, Bengali, Tamil, Latin, ...), two
words and three distinct characters. Only for Latin-script words does it also
apply a conservative gibberish heuristic (a word of five or more letters with no
vowel, or a run of six or more consonants, in more than half of the Latin words).
Limits, stated plainly: it is a lexical floor, not a language or semantic check.
Fluent-looking nonsense in any script passes it, and the Latin heuristic can be
fooled by vowel-bearing keyboard mashing. Non-Latin scripts get no gibberish
heuristic at all, so Hindi nonsense made of real syllables is never flagged. The
pack's 723 junk records are matched exactly by the content signature with or
without the heuristic; no record moved. Confirm the thresholds and whether a
language-aware check is wanted for Hindi.

## 7. Weekly cap when the slot is full for the whole window

Non-exempt surveys whose farmer already had a counted survey in the last 7 days
are deferred; if the window closes while still capped they are dropped
(`cap_suppressed`, 571 in the full-season simulation). Should they instead be
queued for the next free week even if that is outside the send window?
