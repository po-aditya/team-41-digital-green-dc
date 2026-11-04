"""Generate one survey: bounded provider attempts, assembly, validation, fallback.

Every attempt is accounted for (usage and cost), including attempts whose
output was unusable. Deterministic providers are never retried; non-retryable
provider errors stop the attempt loop early. No exception from a provider or
from validation escapes this module.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from mel_agent.config import Settings
from mel_agent.contracts import SchemaRegistry
from mel_agent.generation.catalog import QUESTION_CATALOG, CoverageError, allowed_intents, normalise_options, render_item, slots_for, supported_language
from mel_agent.llm.budgeted import OwnershipLost
from mel_agent.generation.models import ProviderError, ProviderOutput, SurveyProvider, SurveyRequest
from mel_agent.generation.providers import TemplateProvider
from mel_agent.generation.safety import SafetyReport, check_survey

_ITEM_TYPES = ("survey-single-select", "survey-confirm", "survey-scale")


@dataclass
class GenerationResult:
    survey: dict[str, Any] | None
    accepted: bool
    source: str  # provider name, or "<provider>_fallback_template"
    attempts: list[dict[str, Any]] = field(default_factory=list)
    safety: SafetyReport | None = None
    elapsed_ms: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    estimated_cost_usd: float = 0.0
    failed_attempt_cost_usd: float = 0.0
    requires_approval: bool = False  # free-form content: stored for human approval, never scheduled automatically
    aborted: bool = False  # ownership of the work item was lost: no further attempts were started, nothing may be persisted

    def to_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "source": self.source, "attempts": self.attempts,
                "safety": self.safety.to_dict() if self.safety else None, "elapsed_ms": round(self.elapsed_ms, 2),
                "usage": self.usage, "estimated_cost_usd": self.estimated_cost_usd,
                "failed_attempt_cost_usd": self.failed_attempt_cost_usd, "requires_approval": self.requires_approval, "aborted": self.aborted}


def _freeform_item(request: SurveyRequest, n: int, item: dict[str, Any]) -> dict[str, Any] | None:
    """Gated path only: a model-written question, options from the catalogue. Never auto-scheduled."""
    kind = item.get("type")
    prompt = item.get("prompt")
    if kind not in _ITEM_TYPES or not isinstance(prompt, str):
        return None
    clean: dict[str, Any] = {"item_id": f"q{n}", "type": kind, "prompt": prompt.strip()}
    if kind == "survey-scale":
        lo, hi = item.get("scale_min"), item.get("scale_max")
        if isinstance(lo, bool) or isinstance(hi, bool) or not isinstance(lo, int) or not isinstance(hi, int):
            return None
        clean["scale_min"], clean["scale_max"] = lo, hi
        if "follow_up_at_or_below" in item:
            thr, reason = item.get("follow_up_at_or_below"), item.get("follow_up_reason")
            if isinstance(thr, bool) or not isinstance(thr, int) or not isinstance(reason, str):
                return None
            clean["follow_up_at_or_below"], clean["follow_up_reason"] = thr, reason
        return clean
    options = normalise_options(item.get("options"), request.language)
    if options is None or (kind == "survey-confirm" and len(options) != 2):
        return None
    clean["options"] = options
    return clean


def assemble_survey(request: SurveyRequest, output: ProviderOutput, *, allow_freeform: bool = False) -> tuple[dict[str, Any] | None, str | None]:
    """Build the survey document from provider output.

    Returns (survey, problem). Identity, window and ids come from the pipeline. Items are
    question INTENTS rendered from the catalogue with slots grounded in the insight's structured
    fields; a model cannot supply wording. An item carrying a free-form "prompt" is refused
    (``freeform_question_not_allowed``) unless ``allow_freeform`` is set, in which case the
    caller must route the result to the approval queue, never to scheduling."""
    if not supported_language(request.language) or not isinstance(output.items, list) or not output.items:
        return None, "malformed_provider_output"
    slots = slots_for(request.insight, request.language)
    allowed = set(allowed_intents(request.resolution_type, request.insight.get("concern")))
    items: list[dict[str, Any]] = []
    freeform = False
    seen_intents: set[str] = set()
    for n, item in enumerate(output.items[:3], start=1):
        if not isinstance(item, dict):
            return None, "malformed_provider_output"
        intent = item.get("intent")
        if intent is None:
            if "prompt" not in item:
                return None, "malformed_provider_output"
            if not allow_freeform:
                return None, "freeform_question_not_allowed"
            rendered = _freeform_item(request, n, item)
            if rendered is None:
                return None, "malformed_provider_output"
            freeform = True
            items.append(rendered)
            continue
        if not isinstance(intent, str) or intent not in QUESTION_CATALOG:
            return None, "malformed_provider_output"
        if intent not in allowed:
            return None, "intent_not_grounded_in_insight"
        if intent in seen_intents:
            return None, "duplicate_intent"
        seen_intents.add(intent)
        values = item.get("options")
        option_values: list[str] | None = None
        if values is not None:
            if not isinstance(values, list) or not all(isinstance(v, dict) and isinstance(v.get("value"), str) for v in values):
                return None, "malformed_provider_output"
            option_values = [v["value"] for v in values]
        try:
            items.append(render_item(f"q{n}", intent, request.language, slots, option_values))
        except CoverageError:
            return None, "required_outcome_missing"
        except (KeyError, ValueError):
            return None, "malformed_provider_output"
    rationale = output.rationale if isinstance(output.rationale, str) else ""
    survey = {
        "survey_id": request.survey_id,
        "farmer_id": request.farmer_id,
        "source_insight_ids": [request.insight_id],
        "language": request.language,
        "send_window": request.send_window.to_contract(),
        "items": items,
        "rationale": rationale.strip()[:400] or "Follow-up on advice the farmer received.",
    }
    return survey, ("freeform_requires_approval" if freeform else None)


class SurveyGenerator:
    def __init__(self, settings: Settings, registry: SchemaRegistry, provider: SurveyProvider | None = None,
                 fallback: SurveyProvider | None = None) -> None:
        self.settings = settings
        self.registry = registry
        self.provider = provider or TemplateProvider()
        self.fallback = fallback if fallback is not None else (TemplateProvider() if settings.generation_fallback_to_template else None)
        if self.fallback is not None and self.fallback.name == self.provider.name:
            self.fallback = None

    def _account(self, result: GenerationResult, usage: dict[str, Any] | None, cost: float | None, failed: bool) -> None:
        for k, v in (usage or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                result.usage[k] = result.usage.get(k, 0) + v
        if cost:
            result.estimated_cost_usd += float(cost)
            if failed:
                result.failed_attempt_cost_usd += float(cost)

    def _attempt(self, provider: SurveyProvider, request: SurveyRequest, attempt: int, result: GenerationResult) -> tuple[dict[str, Any] | None, SafetyReport | None, bool]:
        """Returns (survey, report, retryable)."""
        record: dict[str, Any] = {"provider": provider.name, "attempt": attempt}
        if request.may_continue is not None and not request.may_continue():
            record.update({"error": "ownership_lost", "retryable": False})
            result.attempts.append(record)
            result.aborted = True
            return None, None, False
        try:
            output = provider.generate(request, attempt)
        except OwnershipLost:
            record.update({"error": "ownership_lost", "retryable": False})
            result.attempts.append(record)
            result.aborted = True
            return None, None, False
        except ProviderError as exc:
            record.update({"error": str(exc), "retryable": exc.retryable})
            self._account(result, exc.usage, exc.cost_usd, failed=True)
            result.attempts.append(record)
            return None, None, exc.retryable
        except Exception as exc:  # a provider bug must not take the pipeline down
            record.update({"error": f"unexpected {type(exc).__name__}", "retryable": False})
            result.attempts.append(record)
            return None, None, False
        self._account(result, output.usage, output.estimated_cost_usd, failed=False)
        if output.prompt_chars:
            record["prompt_chars"] = output.prompt_chars
        try:
            survey, problem = assemble_survey(request, output, allow_freeform=self.settings.generation_allow_freeform)
            if survey is None:
                record.update({"passed": False, "problems": [problem or "malformed_provider_output"], "latency_ms": output.latency_ms})
                result.attempts.append(record)
                return None, None, True  # a model may pick valid intents on a retry
            report = check_survey(request, survey, self.registry, self.settings.min_relevance_score,
                                  grounded=(problem != "freeform_requires_approval"))
            survey["self_eval"] = report.self_eval()
            if problem == "freeform_requires_approval":
                record["requires_approval"] = True
                result.requires_approval = True
            if report.passed and self.registry.errors("survey", survey):
                report.problems.append("schema_invalid_with_self_eval")
        except Exception as exc:  # validation must never raise out of the generator
            record.update({"passed": False, "problems": [f"validation_error_{type(exc).__name__}"], "latency_ms": output.latency_ms})
            result.attempts.append(record)
            return None, None, True
        record.update({"passed": report.passed, "problems": report.problems, "latency_ms": output.latency_ms})
        result.attempts.append(record)
        # A failed deterministic output cannot be fixed by retrying; model output might be.
        if output.estimated_cost_usd and not report.passed:
            result.failed_attempt_cost_usd += float(output.estimated_cost_usd)
        return survey, report, not getattr(provider, "deterministic", False)

    def generate(self, request: SurveyRequest) -> GenerationResult:
        started = time.perf_counter()
        result = GenerationResult(survey=None, accepted=False, source=self.provider.name)
        last_survey, last_report = None, None
        max_attempts = 1 if getattr(self.provider, "deterministic", False) else self.settings.generation_max_attempts
        for attempt in range(1, max_attempts + 1):
            survey, report, retryable = self._attempt(self.provider, request, attempt, result)
            if survey is not None:
                last_survey, last_report = survey, report
            if report is not None and report.passed:
                result.survey, result.accepted, result.safety = survey, True, report
                break
            if not retryable:
                break
        if not result.accepted and self.fallback is not None and not result.aborted:
            survey, report, _ = self._attempt(self.fallback, request, 1, result)
            if report is not None and report.passed:
                result.survey, result.accepted, result.safety = survey, True, report
                result.source = f"{self.provider.name}_fallback_{self.fallback.name}"
            elif survey is not None:
                last_survey, last_report = survey, report
        if not result.accepted:
            result.survey, result.safety = last_survey, last_report
        result.elapsed_ms = (time.perf_counter() - started) * 1000
        return result
