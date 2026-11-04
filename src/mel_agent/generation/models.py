"""Inputs and outputs of survey generation, independent of the provider."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol, Callable

from mel_agent.rules.timing import SendWindow

# Patterns that suggest someone tried to smuggle instructions into insight text.
_INJECTION_PATTERNS = re.compile(
    r"(ignore (all |the |any )?(previous|prior|above|earlier) (instructions|rules|prompts?)|"
    r"system prompt|you are now|disregard (the|all|your)|act as (an?|the) |"
    r"</?\s*(system|assistant|user|instruction)[^>]*>|^\s*###|\bassistant:|\bprompt:)",
    re.IGNORECASE | re.MULTILINE,
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FORMAT_CHARS = re.compile(r"[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_MARKUP = re.compile(r"[<>{}\[\]`|\\]")


def injection_suspected(text: str | None) -> bool:
    return bool(text) and _INJECTION_PATTERNS.search(text) is not None


def sanitize_text(text: str | None, max_len: int = 240) -> str:
    """Make untrusted free text safe to embed in a prompt or a question stem."""
    if not isinstance(text, str) or not text:
        return ""
    cleaned = _MARKUP.sub(" ", _FORMAT_CHARS.sub("", _CONTROL_CHARS.sub(" ", text)))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > max_len:
        cut = cleaned[:max_len]
        cleaned = cut[: cut.rfind(" ")] if " " in cut else cut
    return cleaned


@dataclass(frozen=True)
class SurveyRequest:
    """Everything a provider may know about the survey it writes."""

    survey_id: str
    insight: dict[str, Any]
    farmer: dict[str, Any] | None
    language: str
    send_window: SendWindow
    asks: str  # rules.json "asks" text for this resolution type
    untrusted_text_flags: dict[str, bool] = field(default_factory=dict)
    # Ownership check supplied by the pipeline: called before EVERY model invocation (first attempt,
    # retries, fallback). False means the caller no longer owns the work item; nothing new is started.
    may_continue: Callable[[], bool] | None = field(default=None, repr=False, compare=False)

    @property
    def insight_id(self) -> str:
        return str(self.insight["insight_id"])

    @property
    def farmer_id(self) -> str:
        return str(self.insight["farmer_id"])

    @property
    def resolution_type(self) -> str:
        return str(self.insight["resolution_type"])

    @property
    def asset_name(self) -> str | None:
        return (self.insight.get("asset") or {}).get("name")

    @property
    def asset_category(self) -> str | None:
        return (self.insight.get("asset") or {}).get("category")

    @classmethod
    def build(cls, survey_id: str, insight: dict[str, Any], farmer: dict[str, Any] | None, language: str,
              send_window: SendWindow, asks: str) -> "SurveyRequest":
        flags = {
            "query_summary": injection_suspected(insight.get("query_summary")),
            "advice_summary": injection_suspected(insight.get("advice_summary")),
        }
        return cls(survey_id, insight, farmer, language, send_window, asks, flags)

    @property
    def any_injection_suspected(self) -> bool:
        return any(self.untrusted_text_flags.values())


@dataclass
class ProviderOutput:
    """What a provider returns: only the parts the model is allowed to write."""

    items: list[dict[str, Any]]
    rationale: str
    provider: str
    raw: str | None = None
    usage: dict[str, Any] | None = None
    latency_ms: float | None = None
    estimated_cost_usd: float | None = None
    prompt_chars: int | None = None


class ProviderError(RuntimeError):
    """A provider attempt failed.

    ``retryable`` says whether another attempt could plausibly succeed (a model
    reply that failed to parse: yes; access denied or an unsupported language: no).
    ``usage`` / ``cost_usd`` carry what the failed attempt still cost, so the
    generator can account for it."""

    def __init__(self, message: str, *, retryable: bool = True, usage: dict[str, Any] | None = None,
                 cost_usd: float | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.usage = usage
        self.cost_usd = cost_usd


class SurveyProvider(Protocol):
    name: str
    deterministic: bool  # same request -> same output; retrying a failure is pointless

    def generate(self, request: SurveyRequest, attempt: int) -> ProviderOutput: ...
