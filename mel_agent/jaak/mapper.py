"""Answer_Mapper: map free text to an Item answer (Req 8, 9, 18.3, 18.7).

Pure and deterministic: no I/O, clock, randomness or locale-dependent calls.
Returns ``Matched(value)`` or ``Unclear(reason)`` only. ``reason`` is internal
and is never shown or logged together with the answer text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Union

from .lexicon import NO_CLASS, NUMBER_WORDS, YES_CLASS
from .models import Item
from .normalize import fold_digits, normalize, tokenize


class UnclearReason(str, Enum):
    EMPTY = "empty"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"
    OUT_OF_RANGE = "out_of_range"
    MULTIPLE_NUMBERS = "multiple_numbers"
    NON_INTEGER = "non_integer"
    NO_NUMBER = "no_number"
    REDACTED = "redacted"


@dataclass(frozen=True)
class Matched:
    value: Union[str, int]


@dataclass(frozen=True)
class Unclear:
    reason: UnclearReason


MapResult = Union[Matched, Unclear]

_MAX_DIGITS = 6
_DECIMAL = re.compile(r"\d[.,]\d|\d\s*(?:point|पॉइंट)\s*\d")
_FRACTION_WORDS = frozenset(
    normalize(w) for w in ("half", "आधा", "साढ़े", "डेढ़", "ढाई", "सवा", "पौन")
)
_NEGATIVE_WORDS = frozenset({"minus"})


def map_select(item: Item, text: str, session_language: str) -> MapResult:
    """Map text to one Option value of a select or confirm Item (Req 8)."""
    key = normalize(text)
    if not key:
        return Unclear(UnclearReason.EMPTY)
    yes = YES_CLASS.get(session_language, frozenset())
    no = NO_CLASS.get(session_language, frozenset())
    matches: list[str] = []
    for option in item.options or []:
        forms = {normalize(option.label), normalize(option.value)}
        if forms & yes:
            forms |= yes
        if forms & no:
            forms |= no
        if key in forms:
            matches.append(option.value)
    if len(matches) == 1:
        return Matched(matches[0])
    if not matches:
        return Unclear(UnclearReason.NO_MATCH)
    return Unclear(UnclearReason.AMBIGUOUS)


def map_scale(item: Item, text: str, session_language: str) -> MapResult:
    """Map text to a single in-range integer of a scale Item (Req 9)."""
    if not text.strip():
        return Unclear(UnclearReason.EMPTY)
    key = fold_digits(normalize(text))
    if not key:
        return Unclear(UnclearReason.EMPTY)
    tokens = tokenize(key)
    if (
        _DECIMAL.search(key)
        or key.startswith("-")
        or any(t in _FRACTION_WORDS or t in _NEGATIVE_WORDS for t in tokens)
    ):
        return Unclear(UnclearReason.NON_INTEGER)
    words = NUMBER_WORDS.get(session_language, {})
    found: set[int] = set()
    for token in tokens:
        if token.isascii() and token.isdigit():
            if len(token) <= _MAX_DIGITS:
                found.add(int(token))
        elif token in words:
            found.add(words[token])
    if not found:
        return Unclear(UnclearReason.NO_NUMBER)
    if len(found) > 1:
        return Unclear(UnclearReason.MULTIPLE_NUMBERS)
    (number,) = found
    if item.scale_min is None or item.scale_max is None:
        return Unclear(UnclearReason.OUT_OF_RANGE)
    if not item.scale_min <= number <= item.scale_max:
        return Unclear(UnclearReason.OUT_OF_RANGE)
    return Matched(number)
