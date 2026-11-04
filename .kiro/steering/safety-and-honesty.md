---
inclusion: always
---

# Safety, honesty and JAAKBOT rules (farmerchat-ui)

These are hard requirements for every task. A judge-facing demo must never
overclaim.

## Never claim (out of scope)
- Real farmer delivery, production FarmerChat integration, live external data
  or weather, regions/languages beyond Bihar + en-IN/hi-IN, replacing RCTs,
  large-scale delivery, other background agents.
- A persistent "SYNTHETIC DATA · SIMULATED DELIVERY" badge is always visible
  and cannot be dismissed.
- Fixed footer on Evidence: "Self-reported, simulated answers. Not causal
  evidence. RCTs remain the verifier."

## Honesty about provenance
- Show the generation provider on every survey: "template, offline" vs
  "Bedrock". Template output must NEVER be presented as Bedrock.
- Show paid-inference status (off by default).
- Requirements panel: each row is Evidenced / Partly / Not shown here, with a
  deep link. Never tick a box the data cannot back.
- Panels with no backend endpoint in this repo (clock, broadcast diffs, stats,
  budget, queues, server-side bottom-sheet) are labelled "simulated in UI, no
  backend endpoint" and sourced from the pack/fixtures, not invented.
- cost_usd is null in reports -> show cost as "not evidenced", never a number.

## JAAKBOT
- Never gives agronomic/veterinary/health advice; never answers outside its
  fixed grammar. For anything else: a fixed phrase that it only helps with the
  survey and can route to a human.
- Deterministic matching: normalise transcript, match ONLY the item's `speech`
  synonyms and keypad digits from render JSON. No free-generated answers.
- No audio recorded/stored/sent by default. Mic only on tap, visible listening
  state, one-click stop, stated in UI. Any cloud STT/TTS is behind an explicit
  off-by-default setting with a clear "audio leaves the browser" indicator.
- Detect missing browser speech support; show "use keypad / simulate-speech
  chips"; never break the flow. Hindi speech marked "needs human review".

## Security
- Render ALL backend strings as text nodes. No innerHTML /
  dangerouslySetInnerHTML. Treat backend data as untrusted though synthetic.
- Operator token entered at runtime, in memory only; never localStorage, URL,
  logs, or the repo. No secrets committed. `.env.example` with VITE_API_BASE.
