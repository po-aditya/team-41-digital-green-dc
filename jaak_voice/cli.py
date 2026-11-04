"""Full scripted call with FakeSTT and FakeTTS: no microphone, no AWS, no network.

    python -m jaak_voice.cli [--scenario 1-mustard-aphid-spray] [--language en-IN|hi-IN|both] [--print-record]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings
from .factory import Components, build
from .orchestrator import CallSession
from .stt import FakeSTT

GREETING_REPLY = {"en-IN": "okay go ahead", "hi-IN": "ठीक है"}


def scripted_answers(survey: dict) -> list:
    out = [GREETING_REPLY[survey["language"]]]
    for item in survey["items"]:
        out.append(str(item["scale_min"]) if item["type"] == "survey-scale" else item["options"][0]["label"])
    return out


def run_scripted_call(scenario: str, language: str, outputs_dir: Path | None = None, verbose: bool = False):
    """Returns (CallSession, record or None, validation errors or None)."""
    settings = Settings(stt="fake", tts="fake", **({"outputs_dir": outputs_dir} if outputs_dir else {}))
    comps: Components = build(settings)
    entry = next(s for s in comps.agent.list_scenarios() if s["scenario"] == scenario)
    survey = comps.agent.get_survey(entry["survey_id"], language)
    comps.stt = FakeSTT(scripted_answers(survey))
    call = CallSession(comps.engine, comps.agent, comps.stt, comps.tts)
    call.start(entry["survey_id"], entry["farmer_id"], language)
    while not call.ended:
        turn = call.next_turn()
        if turn is None:
            break
        if verbose:
            print(f"JAAK: {turn.text}")
        if turn.utterance.expects_reply:
            call.handle_farmer_audio(b"\x00fake-audio")
    return call, call.result(), call.validation_errors()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="jaak_voice.cli")
    ap.add_argument("--scenario", default="1-mustard-aphid-spray")
    ap.add_argument("--language", default="both", choices=["en-IN", "hi-IN", "both"])
    ap.add_argument("--outputs", type=Path, default=None)
    ap.add_argument("--print-record", action="store_true")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    langs = ["en-IN", "hi-IN"] if args.language == "both" else [args.language]
    bad = 0
    for lang in langs:
        print(f"=== {lang} ===")
        call, rec, errs = run_scripted_call(args.scenario, lang, args.outputs, verbose=True)
        ok = rec is not None and not errs
        lat = f"{call.last_latency_ms:.1f} ms" if call.last_latency_ms is not None else "n/a"
        print(f"status={rec and rec['status']} valid={ok} last_latency={lat} counters={call.counters} saved={call.save_result()}")
        if args.print_record and rec:
            print(json.dumps(rec, ensure_ascii=False, indent=2))
        bad += 0 if ok else 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
