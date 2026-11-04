"""Command line: ingest, decide, generate, broadcast, evaluate, demo.

Everything runs offline with the template provider. ``--provider bedrock`` is
accepted only when MEL_ALLOW_PAID_INFERENCE is enabled; nothing here enables it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from mel_agent.config import Settings
from mel_agent.contracts import SchemaRegistry
from mel_agent.main import build_pipeline
from mel_agent.time_utils import format_ist

DEFAULT_START = "2026-11-01T00:00:00+05:30"


def _pipeline(args: argparse.Namespace):
    overrides: dict[str, Any] = {}
    if args.db:
        overrides["database_url"] = f"sqlite:///{Path(args.db).resolve()}"
    if getattr(args, "provider", None):
        overrides["generation_provider"] = args.provider
    settings = Settings(**overrides)
    if settings.generation_provider == "bedrock" and not settings.allow_paid_inference:
        print("ERROR: provider=bedrock requires MEL_ALLOW_PAID_INFERENCE=true (paid inference is off by default)", file=sys.stderr)
        raise SystemExit(2)
    registry = SchemaRegistry(settings.schemas_dir)
    _, pipeline, budget = build_pipeline(settings, registry)
    if getattr(args, "clock", None):
        pipeline.clock.set(args.clock)
    return settings, pipeline, budget


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def cmd_ingest(args):
    _, p, _ = _pipeline(args)
    _print(p.ingest(format_ist(p.clock.now)).to_dict())


def cmd_decide(args):
    _, p, _ = _pipeline(args)
    _print(p.decide_all(format_ist(p.clock.now), limit=args.limit))


def cmd_generate(args):
    _, p, _ = _pipeline(args)
    _print(p.generate_and_schedule(format_ist(p.clock.now), limit=args.limit, language=args.language).to_dict())


def cmd_broadcast(args):
    _, p, _ = _pipeline(args)
    _print(p.run_broadcaster(args.until, args.step_minutes))
    _print(p.summary())


def cmd_evaluate(args):
    from mel_agent.evaluation.golden import evaluate_golden, render_markdown

    _, p, _ = _pipeline(args)
    report = evaluate_golden(p.paths, p.rules, p.calendar, p.registry, p.settings, language=args.language).to_dict()
    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "golden_evaluation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (out_dir / "golden_evaluation.md").write_text(render_markdown(report), encoding="utf-8")
        print(f"wrote {out_dir / 'golden_evaluation.json'} and .md", file=sys.stderr)
    _print({k: v for k, v in report.items() if k != "mismatches"} | {"mismatches": report["mismatches"]})


def cmd_run_all(args):
    _, p, _ = _pipeline(args)
    now = format_ist(p.clock.now)
    out = {"ingest": p.ingest(now).to_dict(), "decide": p.decide_all(now), "generate": p.generate_and_schedule(now, limit=args.limit, language=args.language).to_dict()}
    if args.until:
        out["broadcast"] = p.run_broadcaster(args.until, args.step_minutes)
    out["summary"] = p.summary()
    _print(out)


def cmd_budget(args):
    """Inspect the spend ledger, or reconcile one unresolved reservation against the AWS bill."""
    from mel_agent.budget import BudgetError

    _, _, budget = _pipeline(args)
    try:
        if args.action == "status":
            _print({"status": budget.status().to_dict(), "unresolved": budget.unresolved()})
        elif args.action == "reconcile":
            if args.reservation_id is None or args.actual_usd is None:
                print("ERROR: reconcile needs --reservation-id and --actual-usd", file=sys.stderr)
                raise SystemExit(2)
            amount = budget.reconcile(args.reservation_id, args.actual_usd, args.note or "manual reconciliation")
            _print({"reconciled_usd": amount, "status": budget.status().to_dict()})
    except BudgetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)


def cmd_demo(args):
    from mel_agent.demo import run_demo

    settings, p, budget = _pipeline(args)
    result = run_demo(p, budget, settings)
    if args.out:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        (Path(args.out) / "demo_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        print(f"wrote {Path(args.out) / 'demo_result.json'}", file=sys.stderr)
    _print(result)
    failed = [k for k, v in result["cases"].items() if not v.get("passed")]
    if failed:
        print(f"DEMO CASES FAILED: {', '.join(failed)}", file=sys.stderr)
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mel_agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="SQLite file (default from MEL_DATABASE_URL)")
    ap.add_argument("--clock", help=f"Simulated clock start, IST (default {DEFAULT_START})", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ingest", help="load the participant pack into the store").set_defaults(fn=cmd_ingest)
    d = sub.add_parser("decide", help="run eligibility over ingested insights"); d.add_argument("--limit", type=int); d.set_defaults(fn=cmd_decide)
    g = sub.add_parser("generate", help="generate + schedule surveys for eligible insights")
    g.add_argument("--limit", type=int); g.add_argument("--language"); g.add_argument("--provider", choices=["template", "bedrock"], default=None)
    g.set_defaults(fn=cmd_generate)
    b = sub.add_parser("broadcast", help="advance the simulated clock and deliver"); b.add_argument("--until", required=True); b.add_argument("--step-minutes", type=int, default=60)
    b.set_defaults(fn=cmd_broadcast)
    e = sub.add_parser("evaluate", help="golden-set evaluation"); e.add_argument("--language", default="en-IN"); e.add_argument("--out", help="directory for JSON + Markdown report")
    e.set_defaults(fn=cmd_evaluate)
    r = sub.add_parser("run-all", help="ingest + decide + generate (+ broadcast)")
    r.add_argument("--limit", type=int); r.add_argument("--language"); r.add_argument("--until"); r.add_argument("--step-minutes", type=int, default=60)
    r.set_defaults(fn=cmd_run_all)
    m = sub.add_parser("demo", help="eight end-to-end demonstration cases, fully offline"); m.add_argument("--out", help="directory for demo_result.json")
    m.set_defaults(fn=cmd_demo)
    bu = sub.add_parser("budget", help="spend ledger status, or reconcile an unresolved reservation")
    bu.add_argument("action", choices=["status", "reconcile"]); bu.add_argument("--reservation-id"); bu.add_argument("--actual-usd", type=str)
    bu.add_argument("--note"); bu.set_defaults(fn=cmd_budget)

    args = ap.parse_args(argv)
    from mel_agent.pipeline import PipelineError

    try:
        args.fn(args)
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
