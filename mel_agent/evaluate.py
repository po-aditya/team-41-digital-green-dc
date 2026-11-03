"""Scores the agent against Digital Green's golden set.

Dimensions:
- decision:   survey or not, and the rule (R1-R8), vs the golden set
- timeliness: send window exact match, and within one day
- channel:    first channel vs golden channel
- format:     survey JSON valid, 1-3 items, labels <= 20 chars, right script
- relevance:  LLM judge with the golden survey as reference (0-1)
- safety:     no new advice, no personal information
- speed:      seconds per survey, batch wall time, tokens
- gate:       nothing that failed checks was handed to the scheduler
"""
import json
import statistics
import time
from datetime import datetime, timedelta

from . import checker, config, data, llm, pipeline, rules, writer

EVAL_SCHEMA = {
    "type": "object",
    "required": ["relevance", "matches_reference_intent", "gives_new_advice", "asks_personal_info", "notes"],
    "properties": {
        "relevance": {"type": "number", "description": "0-1: questions check this farmer's specific advice and outcome."},
        "matches_reference_intent": {"type": "number", "description": "0-1: covers what the reference survey checks (adoption and outcome)."},
        "gives_new_advice": {"type": "boolean"},
        "asks_personal_info": {"type": "boolean"},
        "notes": {"type": "string"},
    },
}
EVAL_SYSTEM = """You grade follow-up surveys for Digital Green's MEL team. The survey checks whether a farmer used
FarmerChat's advice and whether it worked. You get the insight, a reference survey written by Digital Green, and the
candidate survey. Wording may differ from the reference; judge meaning. Be strict and consistent."""


def judge_vs_golden(insight, expected_items, survey, usage):
    user = (f"Insight: {json.dumps({k: insight.get(k) for k in ('asset', 'query_summary', 'advice_summary', 'resolution_type')}, ensure_ascii=False)}\n"
            f"Reference survey: {json.dumps(expected_items, ensure_ascii=False)}\n"
            f"Candidate survey ({survey['language']}): {json.dumps(survey['items'], ensure_ascii=False)}\n\nCall grade_survey.")
    return llm.call_tool(config.CHECKER_MODEL, EVAL_SYSTEM, user, "grade_survey", "Return the grade.",
                         EVAL_SCHEMA, usage, max_tokens=2000)


def _close(a, b, tol=timedelta(days=1)):
    return abs(rules.parse_ts(a) - rules.parse_ts(b)) <= tol


def run(name, policy=rules.DEFAULT_POLICY, language="en-IN", limit=None, use_llm=True, workers=None, log=print):
    golden = data.golden()[:limit] if limit else data.golden()
    t0 = time.time()
    if use_llm:
        results, stats = pipeline.run_batch([g["insight"] for g in golden], language=language, policy=policy,
                                            workers=workers)
    else:
        results = [{"decision": rules.decide(g["insight"], policy).to_dict(), "status": None} for g in golden]
        stats = {}
    eval_usage = llm.Usage()
    cases = []
    for g, r in zip(golden, results):
        exp, d = g["expected"], r["decision"]
        case = {"golden_id": g["golden_id"], "insight_id": g["insight_id"], "expected_survey": exp["survey"],
                "agent_survey": d["survey"], "expected_rule": exp["rule"], "agent_rule": d["rule"],
                "status": r.get("status")}
        if exp["survey"] and d["survey"]:
            ew, aw = exp["send_window"], d["send_window"]
            case["window_exact"] = (aw["not_before"], aw["not_after"]) == (ew["start"], ew["end"])
            case["window_within_1_day"] = _close(aw["not_before"], ew["start"]) and _close(aw["not_after"], ew["end"])
            case["channel_match"] = d["channel_order"][0]["channel"] == exp["channel"]
        s = r.get("survey")
        if use_llm and s:
            case["format_ok"] = not checker.deterministic(s)
            case["items"] = len(s["items"])
            case["self_check"] = r["check"]
            case["scheduled"] = r["status"] == "scheduled"
            case["handoff_present"] = r.get("handoff") is not None
            if exp["survey"]:
                try:
                    v = judge_vs_golden(g["insight"], exp["items"], s, eval_usage)
                    case.update(relevance=float(v["relevance"]), intent=float(v["matches_reference_intent"]),
                                safe=not v["gives_new_advice"] and not v["asks_personal_info"], judge_notes=v["notes"])
                except Exception as e:  # noqa: BLE001
                    case["judge_error"] = str(e)[:200]
            case["survey"] = s
            case["seconds"] = r["seconds"]
        if r.get("error"):
            case["error"] = r["error"]
        cases.append(case)

    def rate(key, subset=None):
        vals = [c[key] for c in (subset or cases) if key in c]
        return round(sum(vals) / len(vals), 4) if vals else None

    pos = [c for c in cases if c["expected_survey"]]
    tp = sum(1 for c in pos if c["agent_survey"])
    fp = sum(1 for c in cases if c["agent_survey"] and not c["expected_survey"])
    secs = [c["seconds"] for c in cases if "seconds" in c]
    gated = [c for c in cases if "scheduled" in c]
    report = {
        "name": name, "policy": policy, "language": language, "golden_cases": len(cases),
        "writer_model": config.WRITER_MODEL, "prompt_version": writer.PROMPT_VERSION, "checker_model": config.CHECKER_MODEL, "min_relevance": config.MIN_RELEVANCE,
        "at": rules.fmt_ts(datetime.now(rules.IST)),
        "scores": {
            "decision_accuracy": round(sum(c["expected_survey"] == c["agent_survey"] for c in cases) / len(cases), 4),
            "rule_accuracy": round(sum(c["expected_rule"] == c["agent_rule"] for c in cases) / len(cases), 4),
            "survey_recall": round(tp / len(pos), 4) if pos else None,
            "survey_precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "window_exact": rate("window_exact"),
            "window_within_1_day": rate("window_within_1_day"),
            "channel_match": rate("channel_match"),
            "format_ok": rate("format_ok"),
            "relevance": rate("relevance"),
            "reference_intent": rate("intent"),
            "safety": rate("safe"),
            "scheduled_rate": rate("scheduled"),
            "expected_surveys_scheduled": round(sum(1 for c in pos if c.get("scheduled")) / len(pos), 4) if pos and use_llm else None,
            "judged_surveys": sum(1 for c in cases if "relevance" in c),
            "errors": sum(1 for c in cases if "error" in c or "judge_error" in c),
            "gate_ok": all(c["scheduled"] == c["handoff_present"] for c in gated) and
                       all(not c["handoff_present"] for c in gated if not (c.get("self_check") or {}).get("passed")),
        },
        "speed": {
            "batch_wall_seconds": round(time.time() - t0, 2),
            "seconds_per_survey_avg": round(statistics.mean(secs), 2) if secs else None,
            "seconds_per_survey_p95": round(sorted(secs)[int(0.95 * (len(secs) - 1))], 2) if secs else None,
            "agent_usage": stats.get("usage"), "eval_judge_usage": eval_usage.to_dict(),
        },
        "status_counts": stats.get("status"),
        "rule_mismatches": [{"golden_id": c["golden_id"], "expected": c["expected_rule"], "agent": c["agent_rule"]}
                            for c in cases if c["expected_rule"] != c["agent_rule"]],
        "cases": cases,
    }
    config.REPORTS.mkdir(parents=True, exist_ok=True)
    (config.REPORTS / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(config.REPORTS / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"name": name, "at": report["at"], "policy": policy, "prompt_version": writer.PROMPT_VERSION if use_llm else None, "language": language,
                            "golden_cases": len(cases), "scores": report["scores"],
                            "seconds_per_survey_avg": report["speed"]["seconds_per_survey_avg"]}) + "\n")
    log(json.dumps({"name": name, "scores": report["scores"], "speed": {k: v for k, v in report["speed"].items()
                                                                         if not k.endswith("usage")}}, indent=1))
    return report
