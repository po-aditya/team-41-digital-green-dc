"""Developer CLI for the JAAK engine (thin wrapper over the five operations).

    python -m mel_agent.jaak.cli run --survey PATH --farmer-id ID [options]

It adds no engine behaviour, no Turn text and no record fields. Exit codes:
0 ok, 1 usage or file problem, 2 JaakError, 3 input ended before the session did.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

from mel_agent import config

from .engine import JaakEngine
from .errors import JaakError, NotEnded
from .models import ReportFailure, Timeout

EXIT_OK, EXIT_USAGE, EXIT_JAAK, EXIT_INPUT_ENDED = 0, 1, 2, 3
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_FARMERS_CSV = config.DATA / "farmers.csv"

# Directive -> failure_code. Events other than Timeout reach the engine as
# ReportFailure; the engine says "not supported yet" until task 11.1.
_DIRECTIVES = {
    "!drop": "voice_call_dropped",
    "!busy": "voice_busy",
    "!noanswer": "voice_no_answer",
    "!expired": "window_expired",
    "!dup": "duplicate_answer",
}


class CliError(Exception):
    """Usage or file problem (exit 1)."""


def _load_json(path: str, what: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as exc:
        raise CliError(f"cannot read {what} {path}: {type(exc).__name__}") from exc
    if not isinstance(doc, dict):
        raise CliError(f"{what} {path} must be a JSON object")
    return doc


def _farmer_from_csv(path: str, farmer_id: str) -> dict:
    try:
        with open(path, encoding="utf-8", newline="") as f:  # read-only
            for row in csv.DictReader(f):
                if row.get("farmer_id") == farmer_id:
                    return dict(row)
    except OSError as exc:
        raise CliError(f"cannot read farmers csv {path}: {type(exc).__name__}") from exc
    raise CliError(f"farmer {farmer_id} not found in {path}")


def _parse_clock(text: str) -> datetime:
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CliError(f"--clock is not an ISO datetime: {text}") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)


def _out_is_inside_pack(out: Path) -> bool:
    resolved = out.resolve()
    pack = Path(config.PACK).resolve()
    return resolved == pack or pack in resolved.parents


def _read_lines_file(path: str) -> Iterator[str]:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as exc:
        raise CliError(f"cannot read answers file {path}: {type(exc).__name__}") from exc
    return iter(lines)


def _interactive_lines() -> Iterator[str]:
    while True:
        try:
            line = input("> ")
        except EOFError:
            return
        yield line


def _send(engine: JaakEngine, sid: str, line: str) -> None:
    """Map one input line to one engine call."""
    text = line.strip()
    if text.startswith("!"):
        head, _, rest = text.partition(" ")
        if head == "!mismatch":
            event = ReportFailure(
                failure_code="identity_mismatch", reported_farmer_id=rest.strip() or None
            )
        elif head in _DIRECTIVES:
            event = ReportFailure(failure_code=_DIRECTIVES[head])
        else:
            event = None
        if event is not None:
            _submit_event(engine, sid, event)
            return
    if text == "":
        _submit_event(engine, sid, Timeout())
        return
    engine.submit_answer(sid, line, utterance_complete=True)


def _submit_event(engine: JaakEngine, sid: str, event) -> None:
    try:
        engine.submit_event(sid, event)
    except NotImplementedError:
        print("not supported yet", file=sys.stderr)


def _play(engine: JaakEngine, sid: str, lines: Iterator[str]) -> Optional[dict]:
    """Print Turns, feed replies, return the record, or None if input ran out."""
    while True:
        turn = engine.next_turn(sid)
        if turn is not None:
            print(f"JAAK: {turn.text}", file=sys.stderr)
            continue
        try:
            return engine.get_response(sid)
        except NotEnded:
            pass
        line = next(lines, None)
        if line is None:
            return None
        _send(engine, sid, line)


def _run(args: argparse.Namespace) -> int:
    survey = _load_json(args.survey, "survey")
    if args.farmer_json:
        farmer = _load_json(args.farmer_json, "farmer json")
    elif args.farmer_id:
        farmer = _farmer_from_csv(args.farmers_csv, args.farmer_id)
    else:
        raise CliError("give --farmer-id or --farmer-json")
    out = Path(args.out) if args.out else None
    if out is not None and _out_is_inside_pack(out):
        raise CliError("--out must not be inside the participant pack")
    if args.clock:
        fixed = _parse_clock(args.clock)
        clock = lambda: fixed  # noqa: E731
    else:
        clock = lambda: datetime.now(IST)  # noqa: E731
    lines = _read_lines_file(args.answers) if args.answers else _interactive_lines()
    name_copy = Path(args.name_copy) if args.name_copy else None  # ignored until 13.1

    engine = JaakEngine(clock=clock, name_copy_path=name_copy)
    sid = engine.start_session(survey, farmer, delivery_attempt=args.delivery_attempt)
    record = _play(engine, sid, lines)
    if record is None:
        print("error: input ended before the session ended", file=sys.stderr)
        return EXIT_INPUT_ENDED
    payload = json.dumps(record, ensure_ascii=False, indent=2)
    if out is None:
        print(payload)
    else:
        try:
            out.write_text(payload + "\n", encoding="utf-8")
        except OSError as exc:
            raise CliError(f"cannot write {out}: {type(exc).__name__}") from exc
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mel_agent.jaak.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="play one survey session")
    run.add_argument("--survey", required=True, help="Survey JSON file")
    run.add_argument("--farmer-id", help="row to read from the farmers CSV")
    run.add_argument("--farmers-csv", default=str(DEFAULT_FARMERS_CSV))
    run.add_argument("--farmer-json", help="Farmer_Record JSON file (instead of --farmer-id)")
    run.add_argument("--name-copy", help="accepted, ignored until task 13.1")
    run.add_argument("--answers", help="scripted mode: one reply per line")
    run.add_argument("--clock", help="fixed ISO datetime for every clock tick")
    run.add_argument("--delivery-attempt", type=int, default=1)
    run.add_argument("--out", help="write the record here instead of stdout")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except JaakError as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_JAAK


if __name__ == "__main__":
    sys.exit(main())
