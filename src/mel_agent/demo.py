"""Eight end-to-end demonstration cases on synthetic data, with no paid inference
and no real messages. Each case records the resulting states and whether the
expected property held, so the run doubles as an acceptance check.
"""

from __future__ import annotations

import json
from typing import Any

from mel_agent.budget.controller import BudgetController, BudgetExceeded, PaidInferenceDisabled
from mel_agent.config import Settings
from mel_agent.contracts import SchemaName
from mel_agent.delivery.bottom_sheet import render_bottom_sheet
from mel_agent.delivery.simulator import ScriptedSimulator
from mel_agent.llm.pricing import ModelPrice, PricingTable, TokenUsage
from mel_agent.pipeline import Pipeline
from mel_agent.rules.scheduling import survey_id_for
from mel_agent.store import Store
from mel_agent.time_utils import format_ist

# Representative insights are picked from the ingested data BY PROPERTY at run time, so the demo
# does not depend on particular ids. The chosen ids are reported in the result.
def _pick(store: Store, predicate) -> str:
    for row in store.iter_insights(only_valid=False):
        try:
            obj = json.loads(row["raw_json"])
        except json.JSONDecodeError:
            obj = {}
        if predicate(row, obj):
            return row["insight_id"]
    raise RuntimeError("no insight in the dataset matches the demo case")


def _needed(obj: dict[str, Any]) -> bool:
    return bool((obj.get("verification") or {}).get("needed"))


def select_cases(store: Store) -> dict[str, str]:
    return {
        # a clean mustard pest-control direct action in Hindi, the mustard-aphid journey of the Vision document
        "1_valid_eligible": _pick(store, lambda r, o: o.get("resolution_type") == "direct_action" and _needed(o) and o.get("concern") == "pest_disease"
                                  and (o.get("asset") or {}).get("name") == "mustard" and o.get("conversation_language") == "hi-IN" and o.get("severity") == "medium"),
        # a greeting / thanks with no agricultural content
        "2_junk_suppressed": _pick(store, lambda r, o: r["schema_valid"] and o.get("decision_episode_type") == "casual" and (o.get("asset") or {}).get("name") is None),
        # a row that fails insight.schema.json
        "3_invalid_quarantined": _pick(store, lambda r, o: r["quarantine_reason"] == "schema_invalid"),
        # critical severity with actionable advice: a human must call
        "4_critical_human": _pick(store, lambda r, o: r["schema_valid"] and o.get("severity") == "critical" and o.get("resolution_type") in ("direct_action", "plan_created")),
        # actionable, verification needed, but created so late that the window starts after 31 March
        "5_temporal_rejected": _pick(store, lambda r, o: r["schema_valid"] and _needed(o) and o.get("resolution_type") in ("direct_action", "plan_created")
                                     and str(o.get("created_at", "")) >= "2027-03-29" and o.get("severity") != "critical"),
        # escalate_to_expert, voice-first farmer, high priority: exercises channel fallback on a busy line
        "6_end_to_end_delivery": _pick(store, lambda r, o: o.get("resolution_type") == "escalate_to_expert" and _needed(o)
                                       and o.get("preferred_channel") == "voice" and o.get("severity") == "high"),
    }


def run_demo(pipeline: Pipeline, budget: BudgetController, settings: Settings) -> dict[str, Any]:
    now = "2026-11-01T00:00:00+05:30"
    pipeline.clock.set(now)
    pipeline.ingest(now)
    results: dict[str, Any] = {}
    store = pipeline.store
    CASES = select_cases(store)

    # Case 1: valid insight -> eligible survey, valid against survey.schema.json.
    r = pipeline.process_insight(CASES["1_valid_eligible"], now)
    survey_row = store.get_survey(survey_id_for(CASES["1_valid_eligible"]))
    survey = json.loads(survey_row["survey_json"]) if survey_row and survey_row["survey_json"] else None
    results["1_valid_eligible"] = {
        "decision": r["decision"]["internal_reason"], "rule": r["decision"]["rule"], "generation": r.get("generation"),
        "survey_schema_valid": bool(survey) and not pipeline.registry.errors(SchemaName.SURVEY, survey),
        "survey_language": survey_row["language"] if survey_row else None, "items": len(survey["items"]) if survey else 0,
        "handoff_state": (store.get_handoff_for_survey(survey_id_for(CASES["1_valid_eligible"])) or {}).get("state"),
        "passed": bool(survey) and r["decision"]["decision"] == "survey" and (r.get("generation") or {}).get("status") == "scheduled",
    }

    # Case 2: junk insight -> suppressed, external no_survey document valid, no survey or hand-off exists.
    r = pipeline.process_insight(CASES["2_junk_suppressed"], now)
    results["2_junk_suppressed"] = {
        "decision": r["decision"]["internal_reason"], "rule": r["decision"]["rule"], "no_survey": r.get("no_survey"),
        "no_survey_schema_valid": r.get("no_survey_schema_valid"),
        "survey_exists": store.get_survey(survey_id_for(CASES["2_junk_suppressed"])) is not None,
        "passed": r["decision"]["internal_reason"] == "junk_insight" and r.get("no_survey_schema_valid") is True
        and store.get_handoff_for_survey(survey_id_for(CASES["2_junk_suppressed"])) is None,
    }

    # Case 3: schema-invalid insight -> quarantined at ingestion, decision R0, nothing generated.
    r = pipeline.process_insight(CASES["3_invalid_quarantined"], now)
    row = store.get_insight(CASES["3_invalid_quarantined"])
    results["3_invalid_quarantined"] = {
        "quarantine_reason": row["quarantine_reason"], "decision": r["decision"]["decision"], "rule": r["decision"]["rule"],
        "survey_exists": store.get_survey(survey_id_for(CASES["3_invalid_quarantined"])) is not None,
        "passed": row["quarantine_reason"] == "schema_invalid" and r["decision"]["decision"] == "quarantined"
        and store.get_handoff_for_survey(survey_id_for(CASES["3_invalid_quarantined"])) is None,
    }

    # Case 4: critical severity -> no survey, human-intervention queue.
    r = pipeline.process_insight(CASES["4_critical_human"], now)
    results["4_critical_human"] = {
        "decision": r["decision"]["internal_reason"], "rule": r["decision"]["rule"], "needs_human": r["decision"]["details"].get("needs_human"),
        "external_reason_code": r["decision"]["external_reason_code"], "no_survey_schema_valid": r.get("no_survey_schema_valid"),
        "in_human_queue": any(d["insight_id"] == CASES["4_critical_human"] for d in store.list_decisions(rule="R2", limit=200).items),
        "passed": r["decision"]["internal_reason"] == "critical_needs_human_call" and r["decision"]["details"].get("needs_human") is True,
    }

    # Case 5: temporal rejection (window would start after 31 March).
    r = pipeline.process_insight(CASES["5_temporal_rejected"], now)
    results["5_temporal_rejected"] = {
        "decision": r["decision"]["internal_reason"], "rule": r["decision"]["rule"], "details": r["decision"]["details"],
        "passed": r["decision"]["internal_reason"] == "window_after_season",
    }

    # Case 6: eligible survey generated, validated, scheduled, delivered through the mock channel and answered.
    sid = survey_id_for(CASES["6_end_to_end_delivery"])
    pipeline.simulator = ScriptedSimulator(pipeline.outcome_codes, settings.simulation_seed, {sid: ["voice_busy", "completed"]})
    r = pipeline.process_insight(CASES["6_end_to_end_delivery"], now)
    handoff = store.get_handoff_for_survey(sid)
    survey6 = json.loads(store.get_survey(sid)["survey_json"])
    sheet = render_bottom_sheet(survey6, "app")
    pipeline.clock.set(handoff["not_before"])
    broadcast = pipeline.run_broadcaster(handoff["expires_at"], step_minutes=15)
    handoff_after = store.get_handoff(handoff["handoff_id"])
    responses = store.list_responses(survey_id=sid, limit=50).items
    results["6_end_to_end_delivery"] = {
        "handoff_id": handoff["handoff_id"], "priority": json.loads(handoff["handoff_json"])["priority"],
        "channel_order": [c["channel"] for c in json.loads(handoff["handoff_json"])["channel_order"]],
        "handoff_schema_valid": not pipeline.registry.errors(SchemaName.SCHEDULE_HANDOFF, json.loads(handoff["handoff_json"])),
        "bottom_sheet_schema_valid": not pipeline.registry.errors(SchemaName.BOTTOM_SHEET, sheet),
        "attempts": [{k: a[k] for k in ("channel", "delivery_attempt", "state", "outcome_status", "failure_code")} for a in store.attempts_for_handoff(handoff["handoff_id"])],
        "responses": [{k: x[k] for k in ("response_key", "channel", "status", "failure_code", "counts_toward_cap")} for x in responses],
        "all_response_records_schema_valid": all(not pipeline.registry.errors(SchemaName.RESPONSE, json.loads(store.get_response(x["response_key"])["record_json"])) for x in responses),
        "final_state": handoff_after["state"], "broadcast_totals": broadcast["totals"],
        "passed": handoff_after["state"] == "answered" and any(x["status"] == "delivery_failed" and x["failure_code"] == "voice_busy" for x in responses)
        and any(x["status"] in ("completed", "partial", "negative_outcome") for x in responses),
    }

    # Case 7: idempotency. Re-processing and re-ticking at the same clock change nothing.
    before = {"surveys": store.survey_counts(), "handoffs": store.handoff_counts(), "responses": store.response_counts(), "attempts": store.attempt_counts()}
    r_again = pipeline.process_insight(CASES["6_end_to_end_delivery"], now)
    r1_again = pipeline.process_insight(CASES["1_valid_eligible"], now)
    tick = pipeline.broadcaster().tick()
    tick2 = pipeline.broadcaster().tick()
    after = {"surveys": store.survey_counts(), "handoffs": store.handoff_counts(), "responses": store.response_counts(), "attempts": store.attempt_counts()}
    results["7_idempotency"] = {
        "reprocess_status": (r_again.get("generation") or {}).get("status"), "reprocess_status_case1": (r1_again.get("generation") or {}).get("status"),
        "tick_changes": {k: v for k, v in tick.to_dict().items() if isinstance(v, int) and v}, "second_tick_changes": {k: v for k, v in tick2.to_dict().items() if isinstance(v, int) and v},
        "counts_before": before, "counts_after": after,
        "passed": before == after and (r_again.get("generation") or {}).get("status") == "already_scheduled",
    }

    # Case 8: Bedrock spending attempt blocked by the $225 cutoff (mock ledger, no AWS).
    results["8_budget_cutoff"] = _budget_demo(store, settings)

    for name, insight_id in CASES.items():
        results[name]["insight_id"] = insight_id
    results_all = {"clock_end": format_ist(pipeline.clock.now), "cases": results, "summary": pipeline.summary(),
                   "all_passed": all(v.get("passed") for v in results.values())}
    return results_all


def _budget_demo(store: Store, settings: Settings) -> dict[str, Any]:
    """Simulate the ledger reaching the cutoff; the next reservation must be refused.

    Uses a synthetic $1-per-token price so the walk to $225 is short. Paid inference is enabled
    on a copy of the settings for the controller only; no invoker exists here, so nothing can call AWS."""
    enabled = settings.model_copy(update={"allow_paid_inference": True})
    pricing = PricingTable({"demo-model": ModelPrice(input=1_000_000.0, output=1_000_000.0)})  # $1 per token
    controller = BudgetController(store, enabled, pricing)
    steps: list[dict[str, Any]] = []
    refused = None
    for n in range(1, 10):
        try:
            res = controller.reserve("demo-model", input_tokens=40, max_output_tokens=40)  # $80 x 1.25 safety = $100 estimate
            controller.settle(res, TokenUsage(input_tokens=40, output_tokens=40))         # settles at $80 actual
            steps.append({"call": n, "settled_usd": 80.0, "committed_after": round(controller.status().committed_usd, 2)})
        except BudgetExceeded as exc:
            refused = {"call": n, "error": str(exc), "committed_usd": round(controller.status().committed_usd, 2)}
            break
    status = controller.status().to_dict()
    disabled_controller = BudgetController(store, settings, pricing)
    try:
        disabled_controller.reserve("demo-model", 1, 1)
        disabled_block = None
    except PaidInferenceDisabled as exc:
        disabled_block = str(exc)
    return {"steps": steps, "refused": refused, "ledger_status": status, "default_settings_block": disabled_block,
            "passed": refused is not None and status["committed_usd"] <= settings.budget_stop_usd and disabled_block is not None}
