"""The agent: insight -> decision -> survey -> self-check -> scheduler hand-off."""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import checker, config, data, llm, rules, writer

LANGUAGE_DEFAULT = None  # None = use the insight's conversation_language


def _clean_items(items):
    """Normalises small model slips that do not change meaning (ids, empty fields)."""
    out = []
    for n, it in enumerate(items[:3], 1):
        item = {"item_id": f"q{n}", "type": it.get("type"), "prompt": (it.get("prompt") or "").strip()}
        if it.get("type") == "survey-scale":
            for k in ("scale_min", "scale_max", "follow_up_at_or_below", "follow_up_reason"):
                if it.get(k) is not None:
                    item[k] = it[k]
        else:
            opts = []
            for o in it.get("options") or []:
                opt = {"value": (o.get("value") or "").strip().lower().replace(" ", "_").replace("-", "_"),
                       "label": (o.get("label") or "").strip()}
                if o.get("follow_up"):
                    opt["follow_up"] = o["follow_up"]
                opts.append(opt)
            item["options"] = opts
        out.append(item)
    return out


def process(insight, language=LANGUAGE_DEFAULT, policy=rules.DEFAULT_POLICY, use_llm_judge=True, max_attempts=2):
    """Runs the full agent for one insight. Never raises; errors are reported in the result."""
    t0 = time.time()
    usage = llm.Usage()
    decision = rules.decide(insight, policy)
    result = {"insight_id": insight.get("insight_id"), "farmer_id": insight.get("farmer_id"),
              "decision": decision.to_dict(), "survey": None, "handoff": None, "no_survey": None,
              "check": None, "status": None, "attempts": 0}
    if not decision.survey:
        result.update(status="no_survey", no_survey=decision.no_survey_record())
        result.update(seconds=round(time.time() - t0, 3), usage=usage.to_dict())
        return result

    lang = language or insight.get("conversation_language") or "en-IN"
    sid = rules.survey_id_for([insight["insight_id"]])
    feedback, survey, verdict, reasons = None, None, None, []
    try:
        for attempt in range(1, max_attempts + 1):
            result["attempts"] = attempt
            draft = writer.write(insight, lang, usage, feedback)
            if draft.get("skip") or not draft.get("items"):
                result.update(status="writer_skipped", check={"reasons": [draft.get("skip_reason") or "writer skipped"]})
                break
            survey = {
                "survey_id": sid, "farmer_id": insight["farmer_id"], "source_insight_ids": [insight["insight_id"]],
                "language": lang, "send_window": decision.send_window,
                "items": _clean_items(draft["items"]),
                "rationale": (draft.get("rationale") or "Follow-up on advice.").strip()[:400],
            }
            det = checker.deterministic(survey)
            verdict = checker.judge(insight, survey, usage) if (use_llm_judge and not det) else None
            ok, reasons = checker.passes(det, verdict)
            survey["self_eval"] = {
                "schema_valid": not data.schema_errors("survey", {k: v for k, v in survey.items() if k != "self_eval"}),
                **({"relevance_score": round(verdict["relevance_score"], 2),
                    "gives_new_advice": bool(verdict["gives_new_advice"]),
                    "asks_personal_info": bool(verdict["asks_personal_info"])} if verdict else {}),
            }
            result["check"] = {"deterministic": det, "judge": verdict, "passed": ok, "reasons": reasons}
            if ok:
                break
            feedback = reasons
        if result["status"] is None:
            result["survey"] = survey
            if result["check"]["passed"]:
                result["status"] = "scheduled"
                result["handoff"] = rules.build_handoff(survey, decision, insight)
                errs = data.schema_errors("schedule_handoff", result["handoff"])
                if errs:
                    result.update(status="rejected", handoff=None)
                    result["check"]["reasons"].append("hand-off schema: " + "; ".join(errs[:3]))
            else:
                result["status"] = "rejected"
    except Exception as e:  # noqa: BLE001 - one bad insight must not stop a batch
        result.update(status="error", error=f"{type(e).__name__}: {e}"[:500])
    result.update(seconds=round(time.time() - t0, 3), usage=usage.to_dict())
    return result


def run_batch(insights, language=LANGUAGE_DEFAULT, policy=rules.DEFAULT_POLICY, workers=None, on_result=None, **kw):
    """Processes many insights in parallel. Returns (results in input order, batch stats)."""
    t0 = time.time()
    results = [None] * len(insights)
    with ThreadPoolExecutor(max_workers=workers or config.WORKERS) as pool:
        futures = {pool.submit(process, ins, language, policy, **kw): n for n, ins in enumerate(insights)}
        # as_completed: on_result sees each result as soon as it finishes, so callers can save it.
        for fut in as_completed(futures):
            n = futures[fut]
            results[n] = fut.result()
            if on_result:
                on_result(results[n])
    total = llm.Usage()
    for r in results:
        u = r["usage"]
        total.calls += u["calls"]
        total.input_tokens += u["input_tokens"]
        total.output_tokens += u["output_tokens"]
        total.seconds += u["seconds"]
        if u["cost_usd"] is not None:
            total.cost_usd = (total.cost_usd or 0.0) + u["cost_usd"]
        for model, m in u["by_model"].items():
            mine = total.by_model.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0})
            for k in ("calls", "input_tokens", "output_tokens"):
                mine[k] += m[k]
            mine["seconds"] = round(mine["seconds"] + m["seconds"], 3)
    surveyed = [r for r in results if r["decision"]["survey"]]
    stats = {
        "insights": len(results),
        "wall_seconds": round(time.time() - t0, 2),
        "status": {s: sum(1 for r in results if r["status"] == s) for s in
                   ("scheduled", "rejected", "writer_skipped", "no_survey", "error")},
        "seconds_per_survey_avg": round(sum(r["seconds"] for r in surveyed) / len(surveyed), 2) if surveyed else None,
        "usage": total.to_dict(),
    }
    return results, stats
