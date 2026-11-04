"""Classifier: assign an UtteranceClass to a farmer reply (Req 8.1, 8.5, 18).

Rules apply in the fixed order of the design's precedence table; the first hit
wins. Implemented now: rule 2 (ANSWER) and rule 9 (UNCLEAR), plus the rule 3
slot (``_pii_hook``, a pass-through). The OPT_OUT, NOT_NOW, SKIP, ADVICE,
AMBIGUOUS and UNCLEAR_REDACTED rules arrive in tasks 10.1, 12.1 and 15.1; the
enum already has every member so those tasks only add rules.

Pure and deterministic. The result never carries the input text: only the
class and, for ANSWER, the mapped Option value or scale integer.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

from .mapper import Matched, map_scale, map_select
from .models import Item


class UtteranceClass(str, Enum):
    ANSWER = "answer"
    UNCLEAR_REDACTED = "unclear_redacted"
    OPT_OUT = "opt_out"
    NOT_NOW = "not_now"
    SKIP = "skip"
    ADVICE = "advice"
    AMBIGUOUS = "ambiguous"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class GreetingReply:
    """Context: the farmer is replying to the greeting."""


@dataclass(frozen=True)
class ItemAnswer:
    """Context: the farmer is answering ``item``."""

    item: Item
    session_language: str


Context = Union[GreetingReply, ItemAnswer]

greeting_reply = GreetingReply
item_answer = ItemAnswer


@dataclass(frozen=True)
class ClassResult:
    cls: UtteranceClass
    value: Optional[Union[str, int]] = None


def _pii_hook(text: str) -> bool:
    """Rule 3 slot: True when text holds PII. Pass-through until task 15.1."""
    return False


def classify(text: str, context: Context) -> ClassResult:
    # Rule 2: a valid answer always wins (Req 18.3).
    if isinstance(context, ItemAnswer):
        item = context.item
        mapper = map_scale if item.type == "survey-scale" else map_select
        result = mapper(item, text, context.session_language)
        if isinstance(result, Matched):
            return ClassResult(UtteranceClass.ANSWER, result.value)
    # Rule 3: PII redaction (filled by task 15.1).
    if _pii_hook(text):
        return ClassResult(UtteranceClass.UNCLEAR_REDACTED)
    # Rules 4 to 8 arrive in tasks 10.1 and 12.1.
    # Rule 9.
    return ClassResult(UtteranceClass.UNCLEAR)
