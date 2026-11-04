"""Closed catalogues for survey construction: answer options AND question intents.

Farmer-visible text is never free text from a model. A survey is a list of
*question intents*; each intent has a vetted question template per language,
a question type and a fixed option set drawn from the answer catalogue. The
only variable parts of a rendered question are grounded slots filled from the
insight's structured fields (asset, concern, expert type) through fixed
glossaries. This is what keeps "douse your crop with antifreeze" (or any other
instruction, dose, substance or data request) out of a question by construction.

A model may choose WHICH intents to ask (from those allowed for the insight's
resolution type); it cannot write wording and it cannot change an intent's answer
set. Every intent declares its REQUIRED outcomes (review-3 finding 3): the answers
that must always be offered so the survey can distinguish success from failure,
unavailability, harm, "not yet" and "could not reach". For every current intent the
required set is the whole answer set, so narrowing is refused rather than biasing the
answers or losing a follow-up signal. Coverage is validated when a survey is
assembled, when it is checked, and again before every send.
Free-form questions are not supported in the automated pipeline (see
generation/generator.py for the gated, approval-only path).

Labels are at most 20 Unicode code points (WhatsApp button limit).
"""

from __future__ import annotations

from typing import Any

# value: (en-IN label, hi-IN label, negative?)  negative = may carry a follow_up reason
ANSWER_CATALOG: dict[str, tuple[str, str, bool]] = {
    "yes": ("Yes", "हाँ", True),
    "no": ("No", "नहीं", True),
    "not_yet": ("Not yet", "अभी नहीं", False),
    "partly": ("Partly", "कुछ हद तक", False),
    "did_it": ("I did it", "कर लिया", False),
    "did_not_check": ("Did not check", "देखा नहीं", False),
    "easy": ("Yes, easily", "हाँ, आसानी से", False),
    "hard": ("Yes, with difficulty", "हाँ, मुश्किल से", False),
    "not_found": ("Could not get it", "नहीं मिला", True),
    "could_not": ("Could not reach", "संपर्क नहीं हुआ", True),
    "not_available": ("Not available", "सामान नहीं मिला", True),
    "too_costly": ("Too costly", "बहुत महँगा", True),
    "no_time": ("No time", "समय नहीं था", False),
    "unclear": ("Did not understand", "समझ नहीं आया", False),
    "not_met": ("Not met yet", "अभी मिले नहीं", False),
    "better": ("Better", "पहले से बेहतर", False),
    "same": ("Same as before", "पहले जैसी", True),
    "worse": ("Worse", "पहले से खराब", True),
    "almost_none": ("Almost none", "लगभग नहीं", False),
    "fewer": ("Fewer than before", "पहले से कम", False),
    "more": ("More than before", "पहले से ज़्यादा", True),
    "no_new_signs": ("No new signs", "नए लक्षण नहीं", False),
    "spreading": ("Spreading", "फैल रही है", True),
    "recovered": ("Recovered", "ठीक हो गया", False),
    "all": ("All steps", "सारे कदम", False),
    "some": ("Some steps", "कुछ कदम", False),
    "none": ("Not started", "अभी शुरू नहीं", True),
    "too_early": ("Too early to say", "अभी कहना मुश्किल", False),
    "need_help": ("Need more help", "और मदद चाहिए", True),
    "no_help_needed": ("No help needed", "मदद नहीं चाहिए", False),
}

FOLLOW_UP_REASONS = ("advice_did_not_work", "crop_or_animal_damaged", "could_not_get_input", "could_not_reach_expert")
_LANG_INDEX = {"en-IN": 0, "hi-IN": 1}

# ---------- grounded slot glossaries (the only variable text in a question) ----------

ASSET_GLOSSARY: dict[str, tuple[str, str]] = {
    "wheat": ("wheat", "गेहूँ"), "mustard": ("mustard", "सरसों"), "lentil": ("lentil", "मसूर"), "potato": ("potato", "आलू"),
    "maize": ("maize", "मक्का"), "gram": ("gram", "चना"), "pea": ("pea", "मटर"), "onion": ("onion", "प्याज़"), "tomato": ("tomato", "टमाटर"),
    "cauliflower": ("cauliflower", "फूलगोभी"), "cabbage": ("cabbage", "पत्तागोभी"), "goat": ("goat", "बकरी"), "cow": ("cow", "गाय"),
    "buffalo": ("buffalo", "भैंस"),
}
GENERIC_ASSET: dict[str | None, tuple[str, str]] = {"crop": ("crop", "फसल"), "livestock": ("animal", "पशु"), None: ("crop or animal", "फसल या पशु")}
CONCERN_GLOSSARY: dict[str | None, tuple[str, str]] = {
    "pest_disease": ("the pest or disease problem", "कीट या रोग की समस्या"), "weather_climate": ("the weather", "मौसम"),
    "growth_issue": ("the growth problem", "बढ़वार की समस्या"), "nutrient_deficiency": ("the nutrient problem", "पोषक तत्वों की कमी"),
    "variety_selection": ("choosing a variety", "किस्म के चुनाव"), "soil_health": ("soil health", "मिट्टी की सेहत"),
    "water_stress": ("water stress", "पानी की कमी"), "storage_post_harvest": ("storage after harvest", "कटाई के बाद भंडारण"),
    "livestock_nutrition": ("feeding", "खान-पान"), "livestock_health": ("animal health", "पशु स्वास्थ्य"), "market_price": ("market prices", "बाज़ार भाव"),
    "weed_management": ("weeds", "खरपतवार"), "breeding_reproduction": ("breeding", "प्रजनन"), "yield_loss": ("yield loss", "उपज की हानि"),
    None: ("the problem", "समस्या"),
}
EXPERT_GLOSSARY: dict[str, tuple[str, str]] = {"vet": ("veterinary doctor", "पशु चिकित्सक"), "agri": ("agriculture expert", "कृषि विशेषज्ञ")}

# ---------- question intents ----------
# intent: type, en template, hi template, options [(value, follow_up)], allowed resolution types, extra condition.
# "required" (added below for every intent) is the set of answer values that must always be offered.
QUESTION_CATALOG: dict[str, dict[str, Any]] = {
    "did_action": {"type": "survey-confirm",
                   "en": "Did you follow FarmerChat's advice about {concern} on your {asset}?",
                   "hi": "क्या आपने अपनी {asset} पर {concern} के बारे में FarmerChat की सलाह पर काम किया?",
                   "options": [("yes", None), ("no", None)], "resolutions": {"direct_action"}},
    "state_now": {"type": "survey-single-select", "en": "How is your {asset} now?", "hi": "अब आपकी {asset} की हालत कैसी है?",
                  "options": [("better", None), ("same", "advice_did_not_work"), ("worse", "crop_or_animal_damaged")],
                  "resolutions": {"direct_action", "wait_and_monitor", "do_not_act", "plan_created"}},
    "barrier": {"type": "survey-single-select", "en": "If you did not do it, what stopped you?", "hi": "अगर नहीं किया, तो क्या रुकावट थी?",
                "options": [("did_it", None), ("too_costly", None), ("not_available", "could_not_get_input"), ("no_time", None), ("unclear", None)],
                "resolutions": {"direct_action", "plan_created"}},
    "input_available": {"type": "survey-single-select", "en": "Was it easy to get what you needed for your {asset}?",
                        "hi": "क्या अपनी {asset} के लिए ज़रूरी सामान आसानी से मिल गया?",
                        "options": [("easy", None), ("hard", None), ("not_found", "could_not_get_input")], "resolutions": {"direct_action"}},
    "pest_count": {"type": "survey-single-select", "en": "How many of the insects are on your {asset} now?", "hi": "अब आपकी {asset} पर ये कीड़े कितने हैं?",
                   "options": [("almost_none", None), ("fewer", None), ("same", "advice_did_not_work"), ("more", "advice_did_not_work")],
                   "resolutions": {"direct_action", "wait_and_monitor"}, "concern": {"pest_disease"}},
    "kept_watching": {"type": "survey-confirm", "en": "Did you keep checking your {asset} as advised?", "hi": "क्या आप सलाह के अनुसार अपनी {asset} पर नज़र रखते रहे?",
                      "options": [("yes", None), ("no", None)], "resolutions": {"wait_and_monitor"}},
    "problem_growing": {"type": "survey-single-select", "en": "Is the problem growing?", "hi": "क्या समस्या बढ़ रही है?",
                        "options": [("no_new_signs", None), ("same", None), ("spreading", "crop_or_animal_damaged")], "resolutions": {"wait_and_monitor"}},
    "need_help": {"type": "survey-single-select", "en": "Do you need more help with this?", "hi": "क्या आपको इस पर और मदद चाहिए?",
                  "options": [("need_help", "advice_did_not_work"), ("no_help_needed", None)],
                  "resolutions": {"wait_and_monitor", "do_not_act", "escalate_to_expert", "direct_action", "plan_created"}},
    "held_off": {"type": "survey-confirm", "en": "Did you hold off as advised for your {asset}?", "hi": "क्या आपने सलाह के अनुसार अपनी {asset} पर कुछ न करके इंतज़ार किया?",
                 "options": [("yes", None), ("no", None)], "resolutions": {"do_not_act"}},
    "plan_progress": {"type": "survey-single-select", "en": "How much of the plan for your {asset} have you done?", "hi": "अपनी {asset} की योजना का कितना काम आपने कर लिया?",
                      "options": [("all", None), ("some", None), ("none", None)], "resolutions": {"plan_created"}},
    "plan_working": {"type": "survey-single-select", "en": "Is the plan working so far?", "hi": "क्या योजना अब तक काम कर रही है?",
                     "options": [("yes", None), ("too_early", None), ("no", "advice_did_not_work")], "resolutions": {"plan_created"}},
    "reached_expert": {"type": "survey-single-select", "en": "Did you reach the {expert} about your {asset}?", "hi": "क्या आप अपनी {asset} के लिए {expert} से मिल पाए?",
                       "options": [("yes", None), ("not_yet", None), ("could_not", "could_not_reach_expert")], "resolutions": {"escalate_to_expert"}},
    "state_after_expert": {"type": "survey-single-select", "en": "How is your {asset} now?", "hi": "अब आपकी {asset} की हालत कैसी है?",
                           "options": [("better", None), ("same", None), ("worse", "crop_or_animal_damaged"), ("not_met", None)],
                           "resolutions": {"escalate_to_expert"}},
    "advice_useful": {"type": "survey-scale", "en": "On a scale of 1 to 5, how useful was the advice for your {asset}?",
                      "hi": "1 से 5 के पैमाने पर, आपकी {asset} के लिए सलाह कितनी उपयोगी थी?",
                      "scale": (1, 5, 1, "advice_did_not_work"), "resolutions": {"direct_action", "wait_and_monitor", "plan_created", "do_not_act"}},
}


# Required outcome coverage: the full answer set for every intent (fixed answer sets, see module docstring).
for _spec in QUESTION_CATALOG.values():
    if _spec["type"] != "survey-scale":
        _spec["required"] = frozenset(v for v, _ in _spec["options"])
del _spec


def required_values(intent: str) -> frozenset[str]:
    """Answer values that a rendered question for this intent must always offer."""
    spec = QUESTION_CATALOG[intent]
    return spec.get("required", frozenset())


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def item_problems(intent: str, item: Any) -> list[str]:
    """Why a rendered item does not match the approved definition of this intent (empty = matches).

    Checks the item type, and for scale intents the exact minimum, maximum, follow-up threshold and
    follow-up reason (review-4 finding 2); for choice intents the required-outcome and follow-up
    coverage. Applied at assembly, before scheduling and when a persisted document is read for delivery."""
    spec = QUESTION_CATALOG[intent]
    if not isinstance(item, dict):
        return ["item_not_an_object"]
    problems: set[str] = set()
    if item.get("type") != spec["type"]:
        problems.add("item_type_mismatch")
    if spec["type"] == "survey-scale":
        lo, hi, thr, reason = spec["scale"]
        if not (_is_int(item.get("scale_min")) and _is_int(item.get("scale_max"))) or item.get("scale_min") != lo or item.get("scale_max") != hi:
            problems.add("scale_definition_mismatch")
        if not _is_int(item.get("follow_up_at_or_below")) or item.get("follow_up_at_or_below") != thr or item.get("follow_up_reason") != reason:
            problems.add("follow_up_signal_missing")
        if "options" in item:
            problems.add("scale_definition_mismatch")
        return sorted(problems)
    problems.update(coverage_problems(intent, item.get("options")))
    return sorted(problems)


def coverage_problems(intent: str, options: list[dict[str, Any]] | None) -> list[str]:
    """Why an option list fails this intent's coverage contract (empty list = complete)."""
    spec = QUESTION_CATALOG[intent]
    if spec["type"] == "survey-scale":
        return []
    if not isinstance(options, list):
        return ["required_outcome_missing"]
    values = {o.get("value") for o in options if isinstance(o, dict)}
    problems: list[str] = []
    if not required_values(intent) <= values:
        problems.append("required_outcome_missing")
    expected_follow_ups = {v: f for v, f in spec["options"] if f}
    for o in options:
        if isinstance(o, dict) and o.get("value") in expected_follow_ups and o.get("follow_up") != expected_follow_ups[o["value"]]:
            problems.append("follow_up_signal_missing")
            break
    return problems


def supported_language(language: str) -> bool:
    return language in _LANG_INDEX


def label_for(value: str, language: str) -> str:
    return ANSWER_CATALOG[value][_LANG_INDEX[language]]


def option(value: str, language: str, follow_up: str | None = None) -> dict[str, Any]:
    """Build a schema-shaped option from the catalogue. Raises KeyError for unknown values."""
    out: dict[str, Any] = {"value": value, "label": label_for(value, language)}
    if follow_up:
        if follow_up not in FOLLOW_UP_REASONS:
            raise ValueError("unknown follow_up reason")
        out["follow_up"] = follow_up
    return out


def slots_for(insight: dict[str, Any], language: str) -> dict[str, str]:
    """Grounded slot values from the insight's structured fields (never its free text)."""
    i = _LANG_INDEX[language]
    asset = insight.get("asset") or {}
    name = asset.get("name")
    asset_text = ASSET_GLOSSARY[name][i] if name in ASSET_GLOSSARY else GENERIC_ASSET.get(asset.get("category"), GENERIC_ASSET[None])[i]
    concern = insight.get("concern")
    concern_text = CONCERN_GLOSSARY.get(concern if concern in CONCERN_GLOSSARY else None)[i]
    expert_kind = "vet" if asset.get("category") == "livestock" else "agri"
    return {"asset": asset_text, "concern": concern_text, "expert": EXPERT_GLOSSARY[expert_kind][i]}


def allowed_intents(resolution_type: str | None, concern: str | None) -> list[str]:
    out = []
    for name, spec in QUESTION_CATALOG.items():
        if resolution_type in spec["resolutions"] and ("concern" not in spec or concern in spec["concern"]):
            out.append(name)
    return out


class CoverageError(ValueError):
    """A requested answer set would drop a required outcome or a follow-up signal."""


def render_item(item_id: str, intent: str, language: str, slots: dict[str, str], option_values: list[str] | None = None) -> dict[str, Any]:
    """Deterministically render one intent into a schema-shaped survey item.

    ``option_values`` (from a model) may only restate the intent's answer set: unknown values
    raise ValueError; a strict subset that would drop a required outcome raises CoverageError.
    Option order and follow-up reasons always come from the catalogue, never from the model."""
    spec = QUESTION_CATALOG[intent]
    prompt = spec["hi" if language == "hi-IN" else "en"].format(**slots)
    item: dict[str, Any] = {"item_id": item_id, "type": spec["type"], "prompt": prompt}
    if spec["type"] == "survey-scale":
        lo, hi, thr, reason = spec["scale"]
        item.update({"scale_min": lo, "scale_max": hi, "follow_up_at_or_below": thr, "follow_up_reason": reason})
        if item_problems(intent, item):  # invariant: the catalogue's own definition must validate
            raise CoverageError("scale definition does not validate")
        return item
    defaults = spec["options"]
    known = {v for v, _ in defaults}
    if option_values is not None:
        requested = set(option_values)
        if not requested <= known or len(option_values) != len(requested):
            raise ValueError("option values are not members of the intent's answer set")
        if not required_values(intent) <= requested:
            raise CoverageError("option values drop a required outcome")
    chosen = [(v, f) for v, f in defaults if option_values is None or v in option_values]
    item["options"] = [option(v, language, f) for v, f in chosen]
    problems = item_problems(intent, item)
    if problems:  # cannot happen with the catalogue's own sets; kept as an invariant check
        raise CoverageError(",".join(problems))
    return item


def rendering_index(language: str) -> dict[str, set[str]]:
    """Every question text the catalogue can produce in a language -> the intents that produce it
    (two intents may share wording; coverage then passes if any of them is satisfied)."""
    i = _LANG_INDEX[language]
    assets = [v[i] for v in ASSET_GLOSSARY.values()] + [v[i] for v in GENERIC_ASSET.values()]
    concerns = [v[i] for v in CONCERN_GLOSSARY.values()]
    experts = [v[i] for v in EXPERT_GLOSSARY.values()]
    out: dict[str, set[str]] = {}
    for name, spec in QUESTION_CATALOG.items():
        tpl = spec["hi" if language == "hi-IN" else "en"]
        for a in assets:
            if "{concern}" in tpl:
                texts = [tpl.format(asset=a, concern=c, expert=experts[0]) for c in concerns]
            elif "{expert}" in tpl:
                texts = [tpl.format(asset=a, concern="", expert=e) for e in experts]
            else:
                texts = [tpl.format(asset=a, concern="", expert="")]
            for text in texts:
                out.setdefault(text, set()).add(name)
    return out


def all_renderings(language: str) -> set[str]:
    """Every question text the catalogue can produce in a language (for send-time grounding checks)."""
    return set(rendering_index(language))


def normalise_options(raw: Any, language: str) -> list[dict[str, Any]] | None:
    """Coerce model-supplied options onto the catalogue (used by the gated free-form path only)."""
    if not isinstance(raw, list) or not (2 <= len(raw) <= 10):
        return None
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            return None
        value = item.get("value")
        if not isinstance(value, str) or value not in ANSWER_CATALOG or value in seen:
            return None
        seen.add(value)
        follow_up = item.get("follow_up")
        if follow_up is not None:
            if not isinstance(follow_up, str) or follow_up not in FOLLOW_UP_REASONS or not ANSWER_CATALOG[value][2]:
                return None
        out.append(option(value, language, follow_up))
    return out
