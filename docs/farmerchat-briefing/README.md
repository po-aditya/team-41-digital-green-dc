# FarmerChat decision briefing

Open `index.html` directly in a browser. The page works offline. It uses inline CSS, JavaScript, and five locally rendered SVG diagrams. Links to public sources need a network connection. Links to the two original Word files need the surrounding project folder.

The page compares five proposed enhancements for a one-day AWS hackathon. It includes the actual Claude document summary, Claude-authored diagrams and workflow outlines, a separate Codex assessment, and an actual Gemini 4 Argon review. Selection controls make a discussion shortlist. They do not approve an application build. Checklist marks are session-only review notes and do not verify implementation.

The independent-review revision separates authorship. Codex originated C1–C5. Claude first received only both complete source texts and the one-day context, summarized each document, and generated A1–A5 independently. After Stage A completed, a separate no-session-persistence call supplied its response, both source texts, the original Codex options, and the prior briefing for Stage B comparison. Stage B returned one Agree and four Qualify verdicts. No Disagree row was invented; substantive disagreements remain in the findings.

The new raw responses are `claude-independent-a-output.txt` and `claude-independent-b-output.txt`. The parsed display data is in `claude-independent-a.json` and `claude-independent-b.json`. Stage A needed one excess closing brace removed before `independent_options` for parsing. Its original stdout is preserved unchanged. Input hashes, scope, sequence, limits, and the parsing note are recorded in `provenance.json`.

The update qualifies the earlier follow-up-first recommendation. It puts the source-aligned scheduler and thin Hindi output ahead of a conditional internal follow-up record. It corrects branching to an unlisted proposal, the database/hosting/IaC map, and the target repository distinction. Claude's claim that eligibility was missing is also qualified: it was already in the Codex baseline workflow, although it was not one of the enhancement titles. The human architect still chooses.

`provenance.json` records source hashes, the inspected public-code commit, model invocation details, output hashes, reading limits, and AWS source links. The raw model responses are preserved in `claude-summary.md`, `claude-diagrams-output.md`, and `gemini-review.md`. `claude-diagrams.json` is the parsed Claude response used to render the diagrams. Codex notes correct model overstatements; the raw responses remain unchanged.

The Technical document explicitly links to `digitalgreenorg/DG_Open`. That older public snapshot is not confirmed as the user's intended current application repository. No application, AWS resource, real farmer delivery, or pilot was implemented or tested here. The prose uses short technical English; formal ASD-STE100 compliance has not been certified.

Independent acceptance tests were written before the page implementation. On this computer, run them from the project root with:

```sh
/Users/dwayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/briefing.acceptance.mjs
```

The runner uses the bundled Playwright package and installed Chrome with an isolated temporary profile. It does not install a browser or use a personal browser profile. Its default screenshots, print PDF, and JSON results go to `/private/tmp/farmerchat-qa`. `BRIEFING_QA_DIR` can set another output directory. A restricted environment may need permission to launch the isolated browser.

See `verification-independent.md` and `security-independent.md` for the new independent checks and their limits. `verification.md` and `security-review.md` record the earlier revision. Only `index.html` is authorized for this GitHub publication. Tests, transcripts, metadata, and reports are saved on a separate local-only evidence branch. The original Word files and existing architecture page are unchanged.
