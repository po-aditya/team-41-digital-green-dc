# jaak_voice

Voice interface for the text-only JAAK engine (`mel_agent/jaak`), built as ports and adapters.
`mel_agent/jaak` is not modified and imports no audio, AWS or Streamlit code.

## Run

```bash
pip install -r requirements.txt -r jaak_voice/requirements.txt
python -m jaak_voice.cli --print-record        # full scripted call, Fakes only: no mic, AWS or network
streamlit run jaak_voice/app.py               # UI
python -m pytest tests/jaak_voice             # smoke tests
```

With no AWS credentials the app falls back to FakeSTT/FakeTTS and shows a banner (use the typed box).
For real speech set `JAAK_VOICE_S3_BUCKET` (Transcribe batch jobs), `AWS_REGION`, and optionally
`JAAK_VOICE_NAME` (default Kajal, neural, hi-IN and en-IN).

## Layout

| File | Role |
|---|---|
| `ports.py` | `DialogueEngine`, `AgentAdapter`, `SpeechToText`, `TextToSpeech` |
| `jaak_engine_adapter.py` | the only file that imports `mel_agent.jaak` |
| `agent_local.py` | `LocalScenarioAdapter`: pack scenarios + `tests/fixtures/jaak/surveys/*.json`, writes to `outputs/` |
| `stt.py`, `tts.py` | `TranscribeSTT`/`FakeSTT`, `PollyTTS`/`FakeTTS` |
| `config.py`, `factory.py` | env settings and the registry that picks each implementation |
| `orchestrator.py` | `CallSession` (no Streamlit/AWS imports), latency and guardrail counters |
| `app.py`, `cli.py` | Streamlit UI and scripted CLI |

Event mapping: recording stopped = utterance complete; silence or empty recording = timeout event;
Stop = call-dropped event. Counters come only from public Turn kinds (advice declined, re-asks);
redaction and injection counters are omitted because the engine exposes no signal for them.
The transcript never echoes the farmer's words.

## Swapping the agent or engine

Each part is chosen by one environment value (`JAAK_VOICE_ENGINE`, `_AGENT`, `_STT`, `_TTS`), either a
built-in name or `package.module:ClassName`.

- **Different upstream agent:** write a class with `list_scenarios`, `get_survey(survey_id, language)`,
  `get_farmer`, `submit_response`, `validate_response` (see `ports.AgentAdapter`) and set
  `JAAK_VOICE_AGENT=mypkg.agent:MyAgent`. It only has to produce Surveys and Farmer_Records and accept
  Response_Records in the same JSON schemas as `data/participant-pack/json/schemas`.
- **Different engine:** implement `ports.DialogueEngine` (five operations returning `Utterance`) and set
  `JAAK_VOICE_ENGINE=mypkg.engine:MyEngine`.
- **Different speech services:** implement `SpeechToText` / `TextToSpeech` the same way.

## Known limits

The current engine does not yet support timeouts or call-dropped events, so silence and Stop are reported
as notices and Stop produces no Response_Record until those engine tasks land.
