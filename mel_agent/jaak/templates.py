"""Fixed template set: loader and load-time validator (Req 7.7).

One JSON file per language lives in ``templates/{language}.json``. Loading
validates every template against Req 2.2, 6.5, 6.6, 7.1 to 7.6 and 14.3, and
checks the Turn-kind composition table. Any violation raises
``TemplateError(template_id, rule)``; nothing is returned on failure, so there
is no partial load.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import LanguageUnavailable, TemplateError

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

ROLES = ("final", "fragment", "closing", "glue")
MAX_CHARS = 200
MAX_WORDS = 20
MIN_SENTENCES = 1
MAX_SENTENCES = 4
TERMINATORS = ".?\u0964"  # period, question mark, danda

# Placeholder slots: name -> the only template id allowed to use it.
PLACEHOLDER_OWNERS: dict[str, str] = {
    "farmer_name": "greeting_named",
    "scale_min": "scale_tail",
    "scale_max": "scale_tail",
}
# Templates that must contain specific placeholders.
REQUIRED_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "greeting_named": ("farmer_name",),
    "scale_tail": ("scale_min", "scale_max"),
}

# Template id -> required role. Every id must be present in every language.
REQUIRED_TEMPLATES: dict[str, str] = {
    "greeting_plain": "final",
    "greeting_named": "final",
    "option_lead_in": "fragment",
    "option_sep": "glue",
    "option_sep_last": "glue",
    "option_close": "glue",
    "option_tail": "final",
    "scale_tail": "final",
    "reask_prefix": "fragment",
    "advice_decline": "final",
    "reprompt": "final",
    "closing_done": "closing",
    "closing_declined": "closing",
    "closing_opted_out": "closing",
}

THANKS_WORDS: dict[str, tuple[str, ...]] = {
    "en-IN": ("thank", "thanks"),
    "hi-IN": ("\u0927\u0928\u094d\u092f\u0935\u093e\u0926", "\u0936\u0941\u0915\u094d\u0930\u093f\u092f\u093e"),
}

# "<L>" stands for a verbatim Survey label or prompt; it is not JAAK text.
_LBL = "<L>"
# Turn-kind compositions evaluated at load. A Turn that expects a reply must
# end with a ``final`` template.
COMPOSITIONS: dict[str, tuple[tuple[str, ...], bool]] = {
    "greeting": (("greeting_plain",), True),
    "greeting_named": (("greeting_named",), True),
    "question_select": (
        ("option_lead_in", _LBL, "option_sep", _LBL, "option_sep_last", _LBL,
         "option_close", "option_tail"),
        True,
    ),
    "question_scale": (("scale_tail",), True),
    "reask_select": (
        ("reask_prefix", "option_lead_in", _LBL, "option_sep", _LBL,
         "option_sep_last", _LBL, "option_close", "option_tail"),
        True,
    ),
    "reask_scale": (("reask_prefix", "scale_tail"), True),
    "advice_decline": (("advice_decline",), True),
    "reprompt": (("reprompt",), True),
    "closing_done": (("closing_done",), False),
    "closing_declined": (("closing_declined",), False),
    "closing_opted_out": (("closing_opted_out",), False),
}

_LANG_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")
_URL_RE = re.compile(r"(?i)(https?://|www\.)")
_MARKDOWN_RE = re.compile(r"[*#`>|_~\[\]]")
_LIST_MARKER_RE = re.compile(r"(?m)^\s*(?:[-+\u2022]\s|\d+[.)]\s)")
_IDENTIFIER_RES = (
    re.compile(r"\b[A-Za-z0-9]+_[A-Za-z0-9_]+\b"),          # snake_case
    re.compile(r"\b[A-Za-z]{1,4}-\d{3,}\b"),                 # S-21102, F-000311
    re.compile(r"(?i)\b(survey|item|farmer|option)[ ]?(id|value)\b"),
)


@dataclass(frozen=True)
class Template:
    id: str
    role: str
    text: str


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    if cp >= 0x1F000 or cp in (0x200D, 0xFE0F, 0x20E3):
        return True
    if 0x2190 <= cp <= 0x21FF or 0x2300 <= cp <= 0x23FF or 0x2600 <= cp <= 0x27BF \
            or 0x2B00 <= cp <= 0x2BFF:
        return True
    return unicodedata.category(ch) == "So" and cp in (0xA9, 0xAE, 0x2122)


def split_sentences(text: str) -> list[str]:
    """Split on ``.``, ``?``, ``।``; trailing text without terminator counts."""
    out: list[str] = []
    buf: list[str] = []
    for ch in text:
        buf.append(ch)
        if ch in TERMINATORS:
            s = "".join(buf).strip()
            if s.strip(TERMINATORS + " "):
                out.append(s)
            buf = []
    tail = "".join(buf).strip()
    if tail.strip(TERMINATORS + " "):
        out.append(tail)
    return out


def _strip_placeholders(text: str) -> str:
    return _PLACEHOLDER_RE.sub("X", text)


def _check_common(tid: str, text: str, *, check_length: bool = True) -> None:
    """Rules shared by every role: markdown, emoji, URL, identifier, length."""
    plain = _strip_placeholders(text)
    if any(r.search(plain) for r in _IDENTIFIER_RES):
        raise TemplateError(tid, "identifier")
    if _MARKDOWN_RE.search(plain) or _LIST_MARKER_RE.search(plain):
        raise TemplateError(tid, "markdown")
    if any(_is_emoji(c) for c in text):
        raise TemplateError(tid, "emoji")
    if _URL_RE.search(text):
        raise TemplateError(tid, "url")
    if len(text) > MAX_CHARS:
        raise TemplateError(tid, "max_chars")
    if not text.strip():
        raise TemplateError(tid, "empty")


def _check_placeholders(tid: str, text: str, language: str) -> None:
    del language
    found = _PLACEHOLDER_RE.findall(text)
    leftover = _PLACEHOLDER_RE.sub("", text)
    if "{" in leftover or "}" in leftover:
        raise TemplateError(tid, "placeholder")
    for name in found:
        if PLACEHOLDER_OWNERS.get(name) != tid:
            raise TemplateError(tid, "placeholder")
    for name in REQUIRED_PLACEHOLDERS.get(tid, ()):
        if name not in found:
            raise TemplateError(tid, "placeholder")


def _check_sentences(tid: str, text: str) -> list[str]:
    sentences = split_sentences(_strip_placeholders(text))
    for s in sentences:
        if len(s.split()) > MAX_WORDS:
            raise TemplateError(tid, "sentence_length")
    return sentences


def _validate_template(t: Template, language: str) -> None:
    _check_common(t.id, t.text)
    _check_placeholders(t.id, t.text, language)
    if t.role == "glue":
        return
    sentences = _check_sentences(t.id, t.text)
    if not sentences:
        raise TemplateError(t.id, "empty")
    if t.role == "final" and not t.text.rstrip().endswith("?"):
        raise TemplateError(t.id, "final_question_end")
    if t.role == "closing":
        if "?" in t.text:
            raise TemplateError(t.id, "closing_question")
        last = sentences[-1].casefold()
        if not any(w.casefold() in last for w in THANKS_WORDS.get(language, ())):
            raise TemplateError(t.id, "closing_thanks")
    if t.id.startswith("greeting") and "JAAK" not in t.text:
        raise TemplateError(t.id, "greeting_name")


def _join(parts: list[Template | str]) -> str:
    """Join with one space, glue attaches to the left neighbour."""
    out = ""
    for p in parts:
        if isinstance(p, str):
            piece, glue = p, False
        else:
            piece, glue = p.text, p.role == "glue"
        if not out or glue:
            out += piece
        else:
            out += " " + piece
    return out


def _check_compositions(templates: Mapping[str, Template]) -> None:
    for kind, (ids, expects_reply) in COMPOSITIONS.items():
        parts: list[Template | str] = [
            "X" if i == _LBL else templates[i] for i in ids
        ]
        # Placeholders and labels are single words for counting purposes.
        text = _strip_placeholders(_join(parts))
        n = len(split_sentences(text))
        if not (MIN_SENTENCES <= n <= MAX_SENTENCES):
            raise TemplateError(f"turn:{kind}", "sentence_count")
        last = templates[ids[-1]]
        if expects_reply and last.role != "final":
            raise TemplateError(f"turn:{kind}", "reply_must_end_final")
        if not expects_reply and last.role != "closing":
            raise TemplateError(f"turn:{kind}", "closing_must_end_closing")


class TemplateSet:
    """Validated, immutable template set for one language."""

    def __init__(self, language: str, templates: Mapping[str, Template]) -> None:
        self.language = language
        self._templates: dict[str, Template] = dict(templates)

    # -- loading ---------------------------------------------------------
    @classmethod
    def load(cls, language: str, directory: Path | None = None) -> "TemplateSet":
        """Load and validate ``templates/{language}.json``.

        Raises ``LanguageUnavailable`` when no file exists and
        ``TemplateError`` on any rule violation (no partial load).
        """
        if not isinstance(language, str) or not _LANG_RE.match(language):
            raise LanguageUnavailable(language if isinstance(language, str) else "")
        path = (directory or TEMPLATE_DIR) / f"{language}.json"
        if not path.is_file():
            raise LanguageUnavailable(language)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise TemplateError(path.name, "invalid_file") from None
        return cls.from_dict(language, raw)

    @classmethod
    def from_dict(cls, language: str, raw: object) -> "TemplateSet":
        """Validate an already-parsed template document."""
        if not isinstance(raw, dict) or raw.get("language") != language \
                or not isinstance(raw.get("templates"), dict):
            raise TemplateError(f"{language}.json", "invalid_file")
        entries = raw["templates"]
        templates: dict[str, Template] = {}
        for tid, body in entries.items():
            if tid not in REQUIRED_TEMPLATES:
                raise TemplateError(str(tid), "unknown_template")
            if not isinstance(body, dict) or not isinstance(body.get("text"), str):
                raise TemplateError(tid, "invalid_template")
            role = body.get("role")
            if role not in ROLES or role != REQUIRED_TEMPLATES[tid]:
                raise TemplateError(tid, "role")
            templates[tid] = Template(tid, role, body["text"])
        for tid in REQUIRED_TEMPLATES:
            if tid not in templates:
                raise TemplateError(tid, "missing_template")
        for tid in REQUIRED_TEMPLATES:  # deterministic order
            _validate_template(templates[tid], language)
        _check_compositions(templates)
        return cls(language, templates)

    # -- access ----------------------------------------------------------
    def get(self, template_id: str) -> Template:
        return self._templates[template_id]

    def text(self, template_id: str) -> str:
        return self._templates[template_id].text

    def ids(self) -> tuple[str, ...]:
        return tuple(self._templates)

    def fill(self, template_id: str, **values: object) -> str:
        """Return template text with placeholder slots filled."""
        return _PLACEHOLDER_RE.sub(
            lambda m: str(values[m.group(1)]), self._templates[template_id].text
        )
