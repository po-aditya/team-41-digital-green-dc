# FarmerChat Contextual MEL Survey Agent (Team 41)

Digital Green × AWS Breaking Barriers 2026 hackathon.

The agent reads the insights FarmerChat extracts from each farmer's conversations and writes a short follow-up survey about the advice that farmer got. Each survey has one to three tap-answer questions in the farmer's language and a send window based on the crop calendar. It is then handed to a scheduler and a simulated app.

Team: Kevin, Jeramiah, Aditya, Allen.

## Repository layout

| Path | Contents |
|---|---|
| `data/participant-pack/` | Digital Green's synthetic data pack, version 1. Start with `index.html` and `README.txt` |
| `data/participant-pack/data/` | Insights (6,999), golden set (150), farmers (300), Bihar rabi crop calendar |
| `data/participant-pack/json/schemas/` | JSON Schemas for insight, survey, schedule hand-off, response, no-survey and app sheet |
| `data/participant-pack/json/rules/` | Baseline rules: which insights get a survey, send windows, channels, priority, weekly cap |
| `mockup/index.html` | Static mockup of the flow, the farmer app sheet and the MEL dashboard |

## Viewing the mockup

Open `mockup/index.html` in a browser. It has no dependencies.

## Environment

- AWS region: `us-west-2`
- Survey writer model: `us.anthropic.claude-sonnet-5-5`
- Checker model: `us.anthropic.claude-haiku-5-5`
- Python 3.12 or later

All data is fully synthetic. No real farmer data is in this repository.
