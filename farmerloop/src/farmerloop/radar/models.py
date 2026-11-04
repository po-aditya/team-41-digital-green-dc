"""Internal demo envelope; official records retain their original schemas."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Scenario:
    scenario_id: str
    synthetic: bool
    description: str
    observation_cutoff: str
    context: dict[str, str]
    source_template: str
    targets: list[dict[str, str]]
    insights: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    surveys: list[dict[str, Any]]
    handoffs: list[dict[str, Any]]
    responses: list[dict[str, Any]]
    expected: dict[str, dict[str, int]]
    variant_notes: str

    def dump(self) -> dict[str, Any]:
        """Independent JSON-serializable snapshot, including fixture oracles."""
        return asdict(self)
