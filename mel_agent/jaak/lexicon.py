"""Lexicon data for the Answer_Mapper (Req 8.3, 9.2).

All entries are stored in already-normalised form (see ``normalize.normalize``),
so chandrabindu is folded to anusvara. Phrase lists are added in later tasks.
"""

from __future__ import annotations

from .normalize import normalize

_EN_YES = ("yes", "yeah", "yep", "yup")
_EN_NO = ("no", "nope")
_HI_YES = (
    "हाँ", "हां", "जी हाँ", "जी हां", "हाँ जी",
    "haan", "haa", "ji haan", "haan ji",
)
_HI_NO = (
    "नहीं", "नही", "नहीं जी", "ना",
    "nahi", "nahin", "ji nahi", "nahi ji",
)

# Class tables keyed by session language; hi-IN also accepts English forms.
YES_CLASS: dict[str, frozenset[str]] = {
    "en-IN": frozenset(normalize(w) for w in _EN_YES),
    "hi-IN": frozenset(normalize(w) for w in _HI_YES + _EN_YES),
}
NO_CLASS: dict[str, frozenset[str]] = {
    "en-IN": frozenset(normalize(w) for w in _EN_NO),
    "hi-IN": frozenset(normalize(w) for w in _HI_NO + _EN_NO),
}

_NUMBER_WORDS_RAW: dict[str, dict[int, tuple[str, ...]]] = {
    "en": {
        0: ("zero",), 1: ("one",), 2: ("two",), 3: ("three",), 4: ("four",),
        5: ("five",), 6: ("six",), 7: ("seven",), 8: ("eight",), 9: ("nine",),
        10: ("ten",),
    },
    "hi": {
        0: ("शून्य",), 1: ("एक",), 2: ("दो",), 3: ("तीन",), 4: ("चार",),
        5: ("पाँच", "पांच"), 6: ("छह", "छः", "छे"), 7: ("सात",), 8: ("आठ",),
        9: ("नौ",), 10: ("दस",),
    },
    "hi_roman": {
        0: ("shunya",), 1: ("ek",), 2: ("do",), 3: ("teen",), 4: ("char",),
        5: ("paanch", "panch"), 6: ("chhe", "chhah", "chah"), 7: ("saat",),
        8: ("aath",), 9: ("nau",), 10: ("das",),
    },
}


def _invert(table: dict[int, tuple[str, ...]]) -> dict[str, int]:
    return {normalize(w): n for n, words in sorted(table.items()) for w in words}


# word -> integer, one table per script.
NUMBER_WORDS_EN: dict[str, int] = _invert(_NUMBER_WORDS_RAW["en"])
NUMBER_WORDS_HI: dict[str, int] = _invert(_NUMBER_WORDS_RAW["hi"])
NUMBER_WORDS_HI_ROMAN: dict[str, int] = _invert(_NUMBER_WORDS_RAW["hi_roman"])

# Session language -> combined word table (both tables always loaded; only the
# session-language table is consulted).
NUMBER_WORDS: dict[str, dict[str, int]] = {
    "en-IN": NUMBER_WORDS_EN,
    "hi-IN": {**NUMBER_WORDS_HI, **NUMBER_WORDS_HI_ROMAN},
}
