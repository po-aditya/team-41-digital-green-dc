"""Self-evaluation before scheduling: deterministic checks plus an LLM judge."""
import json
import math
import re

from . import config, data, llm

DEVANAGARI = re.compile(r"[\u0900-\u097F]")
LATIN = re.compile(r"[A-Za-z]")

# Words that suggest the survey asks for personal information.
PII_PATTERNS = re.compile(
    r"\b(phone|mobile number|aadhaar|aadhar|bank|account number|address|your name|income|salary|rupees|loan)\b"
    r"|फ़ोन नंबर|फोन नंबर|मोबाइल नंबर|आधार|बैंक|खाता संख्या|आपका नाम|आमदनी|रुपये|कर्ज",
    re.IGNORECASE)

JUDGE_SCHEMA = {
    "type": "object",
    "required": ["relevance_score", "gives_new_advice", "contradicts_advice", "asks_personal_info",
                 "language_correct", "issues"],
    "properties": {
        "relevance_score": {"type": "number", "description": "0 to 1. 1 = every question is about this farmer's advice and outcome."},
        "gives_new_advice": {"type": "boolean"},
        "contradicts_advice": {"type": "boolean"},
        "asks_personal_info": {"type": "boolean"},
        "language_correct": {"type": "boolean", "description": "Prompts and labels are natural, correct text in the target language."},
        "issues": {"type": "array", "items": {"type": "string"}, "description": "Short English notes on any problem."},
    },
}

JUDGE_SYSTEM = """You review follow-up surveys for Digital Green's FarmerChat before they are sent to farmers in Bihar.
Judge strictly against the insight. Score relevance_score:
1.0 every question checks whether the farmer used this specific advice or how the problem changed;
0.7 relevant but one question is vague or generic;
0.4 partly about other topics;
0.0 unrelated.
gives_new_advice: true if any question or option tells the farmer what to do, names a product or dose, or teaches something new.
asks_personal_info: true if it asks for names, numbers, money, location details, IDs or photos.
language_correct: false if any prompt or label is not in the target language, is unnatural, or is wrongly translated."""


def deterministic(survey):
    """Checks that need no model. Returns a list of problems (empty = pass)."""
    problems = list(data.schema_errors("survey", survey))
    lang = survey.get("language", "")
    for it in survey.get("items", []):
        text = [it.get("prompt", "")] + [o.get("label", "") for o in it.get("options", [])]
        if lang.startswith("hi") and not all(DEVANAGARI.search(t) for t in text if t):
            problems.append(f"{it.get('item_id')}: hi-IN text must be in Devanagari")
        if lang.startswith("en") and any(DEVANAGARI.search(t) for t in text):
            problems.append(f"{it.get('item_id')}: en-IN text contains Devanagari")
        if any(PII_PATTERNS.search(t) for t in text):
            problems.append(f"{it.get('item_id')}: may ask for personal information")
        if it.get("type") == "survey-confirm" and len(it.get("options", [])) != 2:
            problems.append(f"{it.get('item_id')}: survey-confirm needs exactly 2 options")
        for o in it.get("options", []):
            if len(o.get("label", "")) > 20:
                problems.append(f"{it.get('item_id')}: label '{o.get('label')}' is {len(o['label'])} characters; max 20")
    ids = [it.get("item_id") for it in survey.get("items", [])]
    if len(ids) != len(set(ids)):
        problems.append("item ids repeat")
    return problems


def judge(insight, survey, usage):
    user = (f"Target language: {survey['language']}\n"
            f"Insight: {json.dumps({k: insight.get(k) for k in ('asset', 'query_summary', 'advice_summary', 'resolution_type')}, ensure_ascii=False)}\n"
            f"Survey items: {json.dumps(survey['items'], ensure_ascii=False)}\n\nCall review_survey.")
    out = llm.call_tool(config.CHECKER_MODEL, JUDGE_SYSTEM, user, "review_survey",
                        "Return your review of the survey.", JUDGE_SCHEMA, usage, max_tokens=2000)
    out["relevance_score"] = _clamp_score(out.get("relevance_score"))
    return out


def _clamp_score(value):
    """Clamps the judge's score to 0-1. Anything that is not a finite number becomes 0.0,
    so a garbled score can never pass the threshold (min/max would turn NaN into 1.0)."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(score):
        return 0.0
    return max(0.0, min(1.0, score))


def passes(det_problems, verdict):
    reasons = list(det_problems)
    if verdict:
        # The rule: relevance below MIN_RELEVANCE is rejected. A score equal to it passes.
        score = _clamp_score(verdict.get("relevance_score"))
        if score < config.MIN_RELEVANCE:
            reasons.append(f"relevance {score:.2f} below {config.MIN_RELEVANCE}")
        for flag, msg in (("gives_new_advice", "gives new advice"), ("contradicts_advice", "contradicts the advice"),
                          ("asks_personal_info", "asks for personal information")):
            if verdict.get(flag):
                reasons.append(msg)
        if not verdict.get("language_correct", True):
            reasons.append("language not correct: " + "; ".join(verdict.get("issues", []))[:200])
    return not reasons, reasons
