import json
import uuid

import pytest

from mel_agent.rules.eligibility import decide
from mel_agent.rules.scheduling import build_handoff, channel_order_for, farmerchat_flow_for, handoff_id_for, priority_for, survey_id_for


def test_handoffs_match_worked_scenarios_except_uuids(scenario_dirs, rules, calendar, registry):
    checked = 0
    for d in scenario_dirs:
        if not (d / "schedule_handoff.json").exists():
            continue
        insight = json.loads((d / "insight.json").read_text())
        expected = json.loads((d / "schedule_handoff.json").read_text())
        decision = decide(insight, rules, calendar)
        ours = build_handoff(insight, expected["survey"], decision.send_window, rules)
        for key in ("created_at", "send_window", "send_hours", "channel_order", "frequency_cap", "priority", "expires_at"):
            assert ours[key] == expected[key], (d.name, key)
        assert ours["farmerchat_flow"]["org_id"] == expected["farmerchat_flow"]["org_id"]
        assert ours["farmerchat_flow"]["flow_key"] == expected["farmerchat_flow"]["flow_key"]
        assert ours["farmerchat_flow"]["version"] == expected["farmerchat_flow"]["version"]
        # The pack's UUIDs come from an unpublished namespace; ours are v5 and schema-valid.
        assert uuid.UUID(ours["farmerchat_flow"]["flow_id"]).version == 5
        assert ours["handoff_id"] == expected["handoff_id"]
        assert not registry.errors("schedule_handoff", ours)
        checked += 1
    assert checked == 5


def test_ids_are_deterministic_and_schema_shaped():
    assert survey_id_for("I-004512") == "S-004512" and handoff_id_for("S-004512") == "H-004512"
    odd = survey_id_for("weird-id")
    assert odd == survey_id_for("weird-id") and len(odd) == 12 and odd.startswith("S-")


def test_priority_rules(rules):
    base = {"resolution_type": "direct_action", "severity": "low", "behavioral_intent": "diagnosing"}
    assert priority_for(base, rules) == "normal"
    assert priority_for(dict(base, resolution_type="escalate_to_expert"), rules) == "high"
    assert priority_for(dict(base, severity="high"), rules) == "high"
    assert priority_for(dict(base, behavioral_intent="emergency"), rules) == "high"
    assert priority_for(dict(base, resolution_type="plan_created"), rules) == "low"
    assert priority_for(dict(base, resolution_type="do_not_act", severity="critical"), rules) == "high"  # high beats low


def test_channel_order_steps(rules):
    ins = {"preferred_channel": "whatsapp", "verification": {"method": "whatsapp"}}
    assert channel_order_for(ins, "normal", rules) == [{"channel": "whatsapp", "wait_hours": None}]
    ins = {"preferred_channel": "web", "verification": {"method": "repeat_photo"}}
    assert [c["channel"] for c in channel_order_for(ins, "normal", rules)] == ["web", "app", "whatsapp"]
    assert [c["channel"] for c in channel_order_for(ins, "high", rules)] == ["web", "app", "whatsapp", "voice"]
    order = channel_order_for(ins, "low", rules)
    assert [c["wait_hours"] for c in order] == [48, 48, None]
    ins = {"preferred_channel": "voice", "verification": {"method": "ivr_callback"}}
    assert [c["channel"] for c in channel_order_for(ins, "high", rules)] == ["voice", "whatsapp"]


def test_flow_ids_stable(rules):
    a, b = farmerchat_flow_for("S-00001", rules), farmerchat_flow_for("S-00001", rules)
    assert a == b and a["campaign_id"] == farmerchat_flow_for("S-00002", rules)["campaign_id"]
    assert a["flow_id"] != farmerchat_flow_for("S-00002", rules)["flow_id"]
