"""Pure text normalisation helpers for the Answer_Mapper (Req 8.2, 8.3, 9.2).

Stdlib only, deterministic, no I/O. Never uses ``\\w`` for Devanagari splitting
because combining vowel signs are not word characters under ``re``.
"""

from __future__ import annotations

import unicodedata

# Zero-width characters and soft hyphen removed during normalisation.
_ZERO_WIDTH = frozenset("\u200b\u200c\u200d\ufeff\u00ad")

# Characters stripped (repeatedly) from the end of normalised text.
_TRAILING = frozenset(".,!?;:\u0964")

_CHANDRABINDU = "\u0901"
_ANUSVARA = "\u0902"


def normalize(text: str) -> str:
    """Normalise ``text`` for matching.

    Order: reject non-str; NFKC; casefold; delete zero-width characters; fold
    chandrabindu to anusvara; collapse whitespace; strip; strip trailing
    punctuation repeatedly.
    """
    if not isinstance(text, str):
        raise TypeError("normalize() requires str")
    s = unicodedata.normalize("NFKC", text).casefold()
    s = "".join(ch for ch in s if ch not in _ZERO_WIDTH)
    s = s.replace(_CHANDRABINDU, _ANUSVARA)
    s = " ".join(s.split())
    while s and s[-1] in _TRAILING:
        s = s[:-1].rstrip()
    return s


def fold_digits(text: str) -> str:
    """Map every Unicode decimal digit (incl. Devanagari) to its ASCII digit."""
    out = []
    for ch in text:
        if unicodedata.category(ch) == "Nd":
            out.append(str(unicodedata.digit(ch)))
        else:
            out.append(ch)
    return "".join(out)


def _is_separator(ch: str) -> bool:
    if ch.isspace():
        return True
    # Unicode punctuation (P*) and symbols (S*). Letters, marks (Mn/Mc, which
    # include Devanagari vowel signs and virama) and digits are kept.
    return unicodedata.category(ch)[0] in ("P", "S")


def tokenize(text: str) -> list[str]:
    """Split on whitespace and Unicode punctuation/symbol categories.

    Devanagari words stay intact because combining marks are not separators.
    """
    tokens: list[str] = []
    current: list[str] = []
    for ch in text:
        if _is_separator(ch):
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens
