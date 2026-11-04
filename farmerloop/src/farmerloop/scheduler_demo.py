"""Offline demonstration of durable caps, opt-outs and attempt reservations."""

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from . import config
from .generate_contextual import ContextualSurveyGenerator
from .models import Insight
from .scheduler import IST, Scheduler
from .timing import compute_window


def run(path, *, run_id="demo-protections", reset=False):
    """All inputs/identities are fictional; no delivery, network, or AWS calls."""
    rows = []
    created = datetime(2026, 12, 4, 19, tzinfo=IST)
    now = datetime(2026, 12, 6, 9, tzinfo=IST)
    template = json.loads((config.PARTICIPANT_PACK / "json/scenarios/1-mustard-aphid-spray/insight.json").read_text())
    with Scheduler(path, run_id=run_id) as scheduler:
        if reset:
            scheduler.reset_demo(confirm_run_id=run_id)
        if scheduler.snapshot()["jobs"]:
            raise ValueError("This run already has history. Choose another --run-id or explicitly use --reset for this demo run.")
        surveys = []
        for number, farmer, severity in ((1, "A", "medium"), (2, "A", "medium"),
                                          (3, "A", "high"), (4, "A", "high"),
                                          (5, "B", "medium"), (6, "B", "medium")):
            raw = dict(template, insight_id=f"SIM-SCHED-I-{number}",
                       conversation_id=f"SIM-SCHED-C-{number}", farmer_id=f"SIM-SCHED-F-{farmer}",
                       conversation_language="en-IN", preferred_channel="whatsapp", severity=severity,
                       verification={"needed": True, "timing": "two_to_five_days", "method": "whatsapp"})
            insight = Insight.model_validate(raw)
            window = compute_window(insight.created_at, insight.verification.timing, insight.action_window_days)
            survey = ContextualSurveyGenerator().generate(insight, window)
            scheduler.enqueue(insight, survey, window, now=created)
            surveys.append(survey.survey_id)

        def claim(label, sid):
            result = scheduler.claim(sid, now=now)
            rows.append({"step": label, "decision": result["decision"], "reason": result["reason"]})
            return result

        first = claim("First normal survey", surveys[0])
        claim("Repeated claim for the same survey", surveys[0])
        claim("Second survey while delivery is unresolved", surveys[1])
        now += timedelta(minutes=25)
        scheduler.complete_simulated(first["attempt_id"], "completed", now=now)
        claim("Second normal survey after first was answered", surveys[1])
        high = claim("High priority bypasses weekly cap", surveys[2])
        now += timedelta(minutes=25)
        scheduler.complete_simulated(high["attempt_id"], "farmer_opted_out", now=now)
        claim("Even high priority respects opt-out", surveys[3])
        failure = claim("Different farmer: delivery attempt", surveys[4])
        scheduler.complete_simulated(failure["attempt_id"], "wa_undelivered", now=now)
        pending = claim("Failed delivery did not consume cap", surveys[5])

    # A new SQLite connection represents a restarted process.
    with Scheduler(path, run_id=run_id) as scheduler:
        result = scheduler.claim(surveys[3], now=now)
        rows.append({"step": "Opt-out survives restart", "decision": result["decision"], "reason": result["reason"]})
        result = scheduler.claim(surveys[5], now=now)
        rows.append({"step": "Pending attempt is not resent after restart", "decision": result["decision"], "reason": result["reason"]})
        now += timedelta(minutes=25)
        scheduler.complete_simulated(pending["attempt_id"], "completed", now=now)
        state = scheduler.snapshot()
    return {"label": "SYNTHETIC offline scheduler demonstration — no real messages sent",
            "run_id": run_id, "steps": rows, "counted_surveys": len(state["cap_events"]),
            "opted_out_farmers": len(state["optouts"]), "attempts": len(state["attempts"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="optional persistent SQLite path; otherwise use a temporary database")
    parser.add_argument("--run-id", default="demo-protections")
    parser.add_argument("--reset", action="store_true", help="clear only this named demo- run before running")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.run_id.startswith("demo-"):
        parser.error("The scripted demonstration requires a demo- run ID")
    try:
        if args.db:
            args.db.parent.mkdir(parents=True, exist_ok=True)
            report = run(args.db, run_id=args.run_id, reset=args.reset)
        else:
            with TemporaryDirectory(prefix="farmerloop-scheduler-") as directory:
                report = run(Path(directory) / "demo.sqlite3", run_id=args.run_id, reset=args.reset)
    except ValueError as exc:
        parser.exit(1, f"Demo stopped: {exc}\n")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report["label"])
        for row in report["steps"]:
            print(f"{row['step']}: {row['decision']} ({row['reason']})")
        print(f"Counted surveys: {report['counted_surveys']}; opted-out farmers: {report['opted_out_farmers']}; reserved attempts: {report['attempts']}")


if __name__ == "__main__":
    main()
