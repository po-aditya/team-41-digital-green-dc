# FarmerChat decision briefing

Open `index.html` directly in a browser. The page works offline. It uses inline CSS, JavaScript, and five locally rendered SVG diagrams. Links to public sources need a network connection. Links to the two original Word files need the surrounding project folder.

The page compares five proposed enhancements for a one-day AWS hackathon. It includes the actual Claude document summary, Claude-authored diagrams and workflow outlines, a separate Codex assessment, and an actual Gemini 4 Argon review. Selection controls make a discussion shortlist. They do not approve an application build. Checklist marks are session-only review notes and do not verify implementation.

`provenance.json` records source hashes, the inspected public-code commit, model invocation details, output hashes, reading limits, and AWS source links. The raw model responses are preserved in `claude-summary.md`, `claude-diagrams-output.md`, and `gemini-review.md`. `claude-diagrams.json` is the parsed Claude response used to render the diagrams. Codex notes correct model overstatements; the raw responses remain unchanged.

The Technical document explicitly links to `digitalgreenorg/DG_Open`. That older public snapshot is not confirmed as the user's intended current application repository. No application, AWS resource, real farmer delivery, or pilot was implemented or tested here. The prose uses short technical English; formal ASD-STE100 compliance has not been certified.

Independent acceptance tests were written before the page implementation. On this computer, run them from the project root with:

```sh
/Users/dwayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/briefing.acceptance.mjs
```

The runner uses the bundled Playwright package and installed Chrome with an isolated temporary profile. It does not install a browser or use a personal browser profile. Its default screenshots, print PDF, and JSON results go to `/private/tmp/farmerchat-qa`. `BRIEFING_QA_DIR` can set another output directory. A restricted environment may need permission to launch the isolated browser.

See `verification.md` and `security-review.md` for the independent checks and their limits. The original Word files and existing architecture page are unchanged.
