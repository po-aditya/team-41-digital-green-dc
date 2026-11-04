"""Self-evaluation of a generated survey before it may be scheduled or sent.

Defence in depth, applied to EVERY text field the farmer or an operator can see
(question stems, option values and labels, rationale, and the bottom-sheet
labels derived from them):

1. Structure: the document validates against survey.schema.json; options come
   from the closed answer catalogue (labels are catalogue text, never model text).
2. Characters: only an allow-list of scripts and punctuation. Control, format
   (bidi/zero-width), private-use, surrogate and unassigned code points are
   rejected, as is any script outside Latin + Devanagari.
3. Content: no URLs, handles, phone numbers or long digit runs; no personal-data
   requests; no advice (imperatives, recommendations); no dosage-like quantities;
   no hazardous-substance vocabulary; stems must be questions.
4. Language: hi-IN text must carry Devanagari; en-IN must not.
5. Relevance proxy and identity fields unchanged from the request.

Deterministic only; an LLM-as-judge step would cost money and is not part of the
offline build. The same checks run again in the broadcaster before any send.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

from mel_agent.contracts import SchemaName, SchemaRegistry
from mel_agent.generation.catalog import ANSWER_CATALOG, FOLLOW_UP_REASONS, item_problems, rendering_index, slots_for
from mel_agent.generation.models import SurveyRequest
from mel_agent.generation.templates import ASSET_HI

# ---------- character policy ----------

_ALLOWED_PUNCT = set(" .,;:!?()'\"-–—/%&+’“”‘…")
_ALLOWED_RANGES = (
    (0x0030, 0x0039),  # digits
    (0x0041, 0x005A), (0x0061, 0x007A),  # Latin letters
    (0x00C0, 0x00FF),  # Latin-1 letters (names such as "Chhapra" transliterations)
    (0x0900, 0x097F),  # Devanagari
    (0xA8E0, 0xA8FF),  # Devanagari Extended
)
_BAD_CATEGORIES = {"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp"}


def character_problems(text: str, *, allow_underscore: bool = False) -> list[str]:
    """Return a list of problem codes for characters outside the allow-list."""
    problems: set[str] = set()
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in _BAD_CATEGORIES:
            problems.add("control_or_format_character")
            continue
        if ch in _ALLOWED_PUNCT or (allow_underscore and ch == "_"):
            continue
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _ALLOWED_RANGES):
            continue
        if cat.startswith("Z"):
            problems.add("unusual_whitespace")
        else:
            problems.add("disallowed_script_or_symbol")
    return sorted(problems)


# ---------- content policy ----------

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
URL_OR_HANDLE = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|org|net|in|io|gov)\b|@[a-z0-9_]{3,}|\b[\w.+-]+@[\w-]+\.\w+)", re.I)
LONG_NUMBER = re.compile(r"\d[\d \-]{6,}\d")
LEAKED_INSTRUCTIONS = re.compile(r"(ignore (previous|all|the) |system prompt|as an ai|language model|json object|INSIGHT \(data only\)|assistant:)", re.I)

_PII_EN = re.compile(
    r"\b(phone|mobile( number)?|whatsapp number|aadha+r|voter id|pan card|ration card|address|village name|your name|father'?s name|"
    r"bank|account number|upi|otp|password|pin( code| number)?|income|salary|caste|religion|how old are you|date of birth|loan|debt|land ?record)\b", re.I)
_PII_HI = re.compile(r"(?<![ऀ-ॿ])(फ़ोन|फोन|मोबाइल|आधार|पता|आपका नाम|बैंक|खाता|ओटीपी|पासवर्ड|आय|जाति|धर्म|उम्र|जन्म तिथि|कर्ज़|कर्ज|ज़मीन के कागज़)(?![ऀ-ॿ])")

_ADVICE_EN = re.compile(
    r"\b(you should|you must|you need to|we recommend|we suggest|it is better to|make sure (to|you)|please (apply|spray|use|give|mix|add|sow|irrigate|buy|call)|"
    r"try (applying|spraying|using|giving|mixing)|next time|instead,? (use|apply|spray)|remember to|don'?t forget to|be sure to)\b", re.I)
_ADVICE_EN_IMPERATIVE = re.compile(
    r"^(apply|spray|use|give|mix|add|sow|irrigate|remove|call|buy|keep|stop|avoid|do not|don't|put|feed|dip|dust|burn|drain|flood|cut|prune|wait|visit)\b", re.I)
_ADVICE_HI = re.compile(r"(करें।|करें$|कीजिए|सलाह (है|दी जाती)|ज़रूर (करें|लगाएँ|डालें)|डालें|छिड़कें|लगाएँ|इस्तेमाल करें|खिलाएँ|पिलाएँ)")

# A number followed by a dose-like unit, in either language: surveys ask about actions, they never prescribe amounts.
_UNITS = (r"ml|millilit(re|er)s?|l|lit(re|er)s?|kg|kilo(gram)?s?|g|gram(s)?|gm|mg|%|percent|ppm|acre(s)?|bigha|katha|hectare(s)?|ha|"
          r"spoons?|teaspoons?|tablespoons?|cups?|bags?|packets?|doses?|times|tablets?|drops?|quintals?|tonnes?|tons?|"
          r"मिली|लीटर|किलो|ग्राम|प्रतिशत|एकड़|बीघा|कट्ठा|चम्मच|बैग|पैकेट|खुराक|गोली|बूँद|क्विंटल")
_QUANTITY = re.compile(rf"(?<![\w.])(\d+([.,]\d+)?|[०-९]+)\s?({_UNITS})(?![\w])", re.I)

# Substances that must never appear in a farmer-facing survey (neither as advice nor as an option).
_HAZARD_EN = re.compile(
    r"\b(petrol|gasoline|kerosene|diesel|acid|poison|bleach|mercury|arsenic|cyanide|phorate|monocrotophos|endosulfan|paraquat|"
    r"aluminium phosphide|celphos|thimet|furadan|carbofuran|methyl parathion|dichlorvos|ddt|lindane|chlorpyrifos|rat poison|"
    r"antibiotic|steroid|oxytocin|formalin|lime sulphur|sulphuric|hydrochloric|nitric|caustic|battery)\b", re.I)
_HAZARD_HI = re.compile(r"(?<![ऀ-ॿ])(पेट्रोल|किरोसिन|केरोसिन|मिट्टी का तेल|डीज़ल|डीजल|तेज़ाब|तेजाब|ज़हर|जहर|ब्लीच|पारा|आर्सेनिक|साइनाइड|फ़ोरेट|फोरेट|मोनोक्रोटोफ़ॉस|एंडोसल्फ़ान|पैराक्वाट|सेलफ़ॉस|फ़्यूराडान|ऑक्सीटोसिन|फ़ॉर्मेलिन|बैटरी)(?![ऀ-ॿ])")

MAX_PROMPT_LEN = 300
MAX_RATIONALE_LEN = 400


@dataclass
class SafetyReport:
    schema_valid: bool
    schema_errors: list[str] = field(default_factory=list)
    language_ok: bool = True
    gives_new_advice: bool = False
    asks_personal_info: bool = False
    leaks_instructions: bool = False
    relevance_score: float = 0.0
    item_count: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems

    def self_eval(self) -> dict[str, Any]:
        """The optional self_eval block of survey.schema.json."""
        return {"schema_valid": self.schema_valid, "relevance_score": round(min(max(self.relevance_score, 0.0), 1.0), 3),
                "gives_new_advice": self.gives_new_advice, "asks_personal_info": self.asks_personal_info}

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "passed": self.passed}


def _visible_texts(survey: dict[str, Any]) -> list[tuple[str, str]]:
    """(field, text) for every farmer-visible string. Tolerates malformed structures."""
    out: list[tuple[str, str]] = []
    items = survey.get("items")
    if not isinstance(items, list):
        return out
    for n, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("prompt"), str):
            out.append((f"items[{n}].prompt", item["prompt"]))
        options = item.get("options")
        if isinstance(options, list):
            for k, o in enumerate(options):
                if isinstance(o, dict) and isinstance(o.get("label"), str):
                    out.append((f"items[{n}].options[{k}].label", o["label"]))
    # Option *values* are machine identifiers (schema pattern ^[a-z0-9][a-z0-9_]{0,63}$) and must be
    # catalogue members; they are checked in _catalogue_problems, not as visible text.
    return out


def _operator_texts(survey: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    if isinstance(survey.get("rationale"), str):
        out.append(("rationale", survey["rationale"]))
    return out


def text_problems(text: str, *, language: str, field_name: str, farmer_visible: bool) -> list[str]:
    """All policy problems for one string. Codes are stable and never include the text."""
    problems: list[str] = []
    problems += character_problems(text, allow_underscore=not farmer_visible)
    if URL_OR_HANDLE.search(text) or LONG_NUMBER.search(text) or LEAKED_INSTRUCTIONS.search(text):
        problems.append("leaks_instructions_or_contacts")
    if _PII_EN.search(text) or _PII_HI.search(text):
        problems.append("asks_personal_info")
    if _HAZARD_EN.search(text) or _HAZARD_HI.search(text):
        problems.append("hazardous_substance")
    if _QUANTITY.search(text):
        problems.append("unsupported_quantity")
    if _ADVICE_EN.search(text) or _ADVICE_HI.search(text) or (farmer_visible and _ADVICE_EN_IMPERATIVE.match(text.strip())):
        problems.append("gives_new_advice")
    if farmer_visible and field_name.endswith(".prompt"):
        if not text.strip().endswith(("?", "？")):
            problems.append("prompt_not_a_question")
        if len(text) > MAX_PROMPT_LEN:
            problems.append("prompt_too_long")
        if language == "hi-IN" and not DEVANAGARI.search(text):
            problems.append("wrong_language")
        if language.startswith("en-") and DEVANAGARI.search(text):
            problems.append("wrong_language")
    if field_name == "rationale" and len(text) > MAX_RATIONALE_LEN:
        problems.append("rationale_too_long")
    return problems


def _catalogue_problems(survey: dict[str, Any], language: str) -> list[str]:
    problems: list[str] = []
    items = survey.get("items")
    if not isinstance(items, list):
        return ["items_not_a_list"]
    for item in items:
        if not isinstance(item, dict):
            problems.append("item_not_an_object"); continue
        options = item.get("options")
        if options is None:
            if item.get("type") != "survey-scale":
                problems.append("options_missing")
            else:
                lo, hi = item.get("scale_min"), item.get("scale_max")
                if not (isinstance(lo, int) and isinstance(hi, int) and 0 <= lo < hi and hi - lo <= 9):
                    problems.append("scale_out_of_policy")  # "a number, up to 10 steps"
            continue
        if not isinstance(options, list):
            problems.append("options_not_a_list"); continue
        for o in options:
            if not isinstance(o, dict) or o.get("value") not in ANSWER_CATALOG:
                problems.append("option_not_in_catalogue"); continue
            expected = ANSWER_CATALOG[o["value"]][0 if language != "hi-IN" else 1]
            if o.get("label") != expected:
                problems.append("option_label_not_catalogue_text")
            if "follow_up" in o and (o["follow_up"] not in FOLLOW_UP_REASONS or not ANSWER_CATALOG[o["value"]][2]):
                problems.append("follow_up_not_allowed_on_option")
    return problems


_RENDERINGS: dict[str, dict[str, set[str]]] = {}


def _grounding_problems(survey: dict[str, Any], language: str) -> list[str]:
    """Every question text must be one the catalogue can render in this language, and the item must match
    the approved definition of (one of) the intents that render that text: type, answer set with required
    outcomes and follow-ups, or for scale questions the exact range, threshold and follow-up reason. A
    schema-valid stored document is NOT assumed to be semantically safe."""
    if language not in ("en-IN", "hi-IN"):
        return ["prompt_not_from_catalogue"]
    index = _RENDERINGS.get(language)
    if index is None:  # computed once per language (setdefault would rebuild it on every call)
        index = _RENDERINGS[language] = rendering_index(language)
    problems: list[str] = []
    for item in survey.get("items") or []:
        if not isinstance(item, dict) or not isinstance(item.get("prompt"), str):
            continue
        intents = index.get(item["prompt"])
        if not intents:
            problems.append("prompt_not_from_catalogue")
            continue
        per_intent = [item_problems(name, item) for name in sorted(intents)]
        if all(per_intent):  # no candidate intent is fully covered
            problems.extend(sorted({p for ps in per_intent for p in ps}))
    return problems


def validate_survey_text(survey: dict[str, Any], language: str, *, grounded: bool = True) -> list[str]:
    """Content policy for a survey document alone (no request needed). Used before every send.

    With ``grounded`` (the default and the only mode used before scheduling or sending) every
    question must be a catalogue rendering; the lexical checks below are defence in depth."""
    problems: set[str] = set(_catalogue_problems(survey, language))
    if grounded:
        problems.update(_grounding_problems(survey, language))
    for field_name, text in _visible_texts(survey):
        problems.update(text_problems(text, language=language, field_name=field_name, farmer_visible=True))
    for field_name, text in _operator_texts(survey):
        problems.update(p for p in text_problems(text, language="en-IN", field_name=field_name, farmer_visible=False)
                        if p not in ("asks_personal_info",))  # a rationale may legitimately say "no personal info asked"
    return sorted(problems)


def relevance_proxy(request: SurveyRequest, survey: dict[str, Any]) -> float:
    """Share of items that name the asset or echo the advice (crude relevance proxy)."""
    asset = (request.asset_name or "").lower()
    terms = {asset} if asset else set()
    if request.language == "hi-IN" and asset in ASSET_HI:
        terms.add(ASSET_HI[asset])
    if request.language in ("en-IN", "hi-IN"):
        terms.add(slots_for(request.insight, request.language)["asset"].lower())  # the glossary text that names the asset
    advice_words = {w for w in re.findall(r"[a-z]{5,}", (request.insight.get("advice_summary") or "").lower())
                    if w not in {"advised", "farmer", "recommended", "because", "would", "should", "their", "there", "which", "about"}}
    items = [i for i in (survey.get("items") or []) if isinstance(i, dict) and isinstance(i.get("prompt"), str)]
    if not items:
        return 0.0
    hits = 0
    for item in items:
        prompt = item["prompt"].lower()
        if any(t and t in prompt for t in terms) or any(w in prompt for w in advice_words):
            hits += 1
    first = items[0]["prompt"].lower()
    if hits and (any(t and t in first for t in terms) or any(w in first for w in advice_words)):
        return max(hits / len(items), 0.75)
    return hits / len(items)


def check_survey(request: SurveyRequest, survey: dict[str, Any], registry: SchemaRegistry, min_relevance: float, *, grounded: bool = True) -> SafetyReport:
    issues = registry.errors(SchemaName.SURVEY, survey)
    items = survey.get("items") if isinstance(survey.get("items"), list) else []
    report = SafetyReport(schema_valid=not issues, schema_errors=[f"{i.path}: {i.validator}" for i in issues[:5]], item_count=len(items))
    if issues:
        report.problems.append("schema_invalid")
    content = validate_survey_text(survey, request.language, grounded=grounded)
    report.problems.extend(p for p in content if p not in report.problems)
    report.language_ok = "wrong_language" not in content
    report.asks_personal_info = "asks_personal_info" in content
    report.gives_new_advice = "gives_new_advice" in content
    report.leaks_instructions = "leaks_instructions_or_contacts" in content
    report.relevance_score = relevance_proxy(request, survey)
    if report.relevance_score < min_relevance:
        report.problems.append("low_relevance")
    # Identity fields must be exactly what the pipeline set.
    if survey.get("survey_id") != request.survey_id or survey.get("farmer_id") != request.farmer_id \
            or survey.get("source_insight_ids") != [request.insight_id] or survey.get("language") != request.language:
        report.problems.append("identity_fields_altered")
    if survey.get("send_window") != request.send_window.to_contract():
        report.problems.append("send_window_altered")
    report.problems = sorted(set(report.problems))
    return report
