"""Shared test fixtures: a clean, schema-valid insight builder."""

from __future__ import annotations

from typing import Any

from farmerloop.models import Insight


def insight_dict(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "insight_id": "I-000001",
        "farmer_id": "F-000001",
        "conversation_id": "C-000001",
        "created_at": "2026-12-04T09:00:00+05:30",
        "conversation_language": "hi-IN",
        "location": {"country": "IN", "state": "Bihar", "district": "Patna"},
        "asset": {"name": "wheat", "category": "crop", "growth_stage": None},
        "concern": "pest_disease",
        "behavioral_intent": "procedural_guidance",
        "decision_episode_type": "decision",
        "severity": "medium",
        "query_summary": "Farmer asks about insects on wheat.",
        "advice_summary": "Advised a recommended spray within 2 days.",
        "resolution_type": "direct_action",
        "action_window_days": 2,
        "verification": {"needed": True, "timing": "two_to_five_days", "method": "push"},
        "preferred_channel": "app",
        "quality_flag": "clean",
    }
    base.update(over)
    return base


def make_insight(**over: Any) -> Insight:
    return Insight.model_validate(insight_dict(**over))
