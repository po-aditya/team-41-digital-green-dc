"""Survey writer: turns one insight into one to three tap-answer questions."""
import json
import os

from . import config, data, llm

FOLLOW_UP = ["advice_did_not_work", "crop_or_animal_damaged", "could_not_get_input", "could_not_reach_expert"]

TOOL_SCHEMA = {
    "type": "object",
    "required": ["skip", "rationale", "items"],
    "properties": {
        "skip": {"type": "boolean", "description": "True only if no meaningful question can be asked about this advice."},
        "skip_reason": {"type": "string"},
        "rationale": {"type": "string", "description": "English, under 300 characters. Why this survey, why now."},
        "items": {
            "type": "array", "minItems": 0, "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["item_id", "type", "prompt"],
                "properties": {
                    "item_id": {"type": "string", "description": "q1, q2, q3"},
                    "type": {"type": "string", "enum": ["survey-confirm", "survey-single-select", "survey-scale"]},
                    "prompt": {"type": "string"},
                    "options": {"type": "array", "items": {
                        "type": "object", "required": ["value", "label"],
                        "properties": {"value": {"type": "string"}, "label": {"type": "string"},
                                       "follow_up": {"type": "string", "enum": FOLLOW_UP}}}},
                    "scale_min": {"type": "integer"}, "scale_max": {"type": "integer"},
                    "follow_up_at_or_below": {"type": "integer"},
                    "follow_up_reason": {"type": "string", "enum": FOLLOW_UP},
                },
            },
        },
    },
}

SYSTEM = """You write follow-up surveys for Digital Green's FarmerChat, an advisory assistant for small-scale farmers in Bihar, India.
A farmer got advice from FarmerChat. You write a short survey that checks whether they used THAT advice and whether it worked.

Rules:
- 1 to 3 questions. Fewer is better if they cover it. Each answered with one tap.
- Ask only about the advice in the insight. Name the crop or animal and the problem in plain words a farmer uses.
- Never give new advice, instructions, product names or doses. Never contradict the advice.
- Never ask for personal information: no names, phone numbers, money amounts, addresses, ID numbers, land records, photos.
- Question types: survey-confirm (exactly 2 options, yes/no), survey-single-select (2 to 5 options), survey-scale (scale_min and scale_max, no options).
- Option "value": lowercase English snake_case, e.g. yes, no, fewer, more, not_started.
- Option "label": at most 20 characters INCLUDING spaces and matras, in the survey language. Count carefully.
- Mark an option with "follow_up" when choosing it means the advice failed or harm happened:
  advice_did_not_work, crop_or_animal_damaged, could_not_get_input, could_not_reach_expert.
- Write "prompt" and "label" in the requested survey language only. For hi-IN use simple, everyday spoken Hindi in Devanagari,
  with local words farmers use (for example माहू for aphids). Do not mix in English words when a common Hindi word exists.
- "rationale" is always English and is never shown to the farmer.
- Set "skip" true only if the insight gives nothing concrete to ask about.

What to ask, by resolution type:
{asks}{patterns}"""

# Prompt v2: Digital Green's MEL question patterns, taken from the golden set. Standard answer
# sets let the MEL team count and compare answers across farmers, so follow them closely.
PATTERNS = """

Use Digital Green's standard MEL question patterns. Fill in the specific action, sign, crop or animal from the
insight in short plain words. Keep these answer sets (translated for hi-IN) so answers can be compared across farmers:
- direct_action:
  q1 survey-single-select "Did you <do the advised action>?" -> Yes / Not yet / No
  q2 survey-single-select "How is your <crop or animal> now?" -> Better / Same (follow_up advice_did_not_work) / Worse (follow_up crop_or_animal_damaged)
  q3 only if the action needs buying an input or extra work: "If not, what stopped you?" -> Too costly / Not available nearby (follow_up could_not_get_input) / No time / Did not understand
- do_not_act:
  q1 survey-confirm "Did you <hold off as advised>?" -> Yes / No
  q2 survey-single-select "How is your <crop or animal> now?" -> Better / Same (follow_up advice_did_not_work) / Worse (follow_up crop_or_animal_damaged)
- plan_created:
  q1 survey-single-select "How much of the plan have you done?" -> All steps / Some steps / Not started
  q2 survey-single-select "Is the plan working so far?" -> Yes / Too early to say / No (follow_up advice_did_not_work)
- wait_and_monitor:
  q1 survey-single-select "Have you seen <the specific sign the farmer was told to watch for>?" -> Yes (follow_up advice_did_not_work) / No / Did not check
  q2 survey-confirm "Do you need more help?" -> Yes (follow_up advice_did_not_work) / No
- escalate_to_expert:
  q1 survey-single-select "Did you <meet or call the advised expert>?" -> Yes / Not yet / Could not reach (follow_up could_not_reach_expert)
  q2 survey-single-select "Did their advice help?" -> Yes / No (follow_up advice_did_not_work) / Not met yet
The outcome question is about the crop or animal the farmer cares about (for fodder advice, ask about the animal)."""
# Prompt v3: fixes what the self-check judge marked "relevant but one question is vague or generic"
# (relevance 0.70, below the 0.8 threshold) in the seed-7 sample and the golden set:
# - wait_and_monitor: the bare "Do you need more help?" question did not check the watching or the outcome.
# - generic outcome questions ("How is your crop now?") and unnamed references ("the advised stage").
# - literal, formal Hindi ("खुद को रोका") flagged as unnatural.
# Answer sets stay the same as v2 so answers remain comparable with Digital Green's MEL patterns.
PATTERNS_V3 = """

Use Digital Green's standard MEL question patterns. Fill in the specific action, sign, crop or animal from the
insight in short plain words. Keep these answer sets (translated for hi-IN) so answers can be compared across farmers.
Every question must be about THIS advice: name the action, the sign or the problem from the insight in the question.
- direct_action:
  q1 survey-single-select "Did you <do the advised action, described concretely>?" -> Yes / Not yet / No
  q2 survey-single-select "How is the <problem the advice was for> in your <crop or animal> now?" -> Better / Same (follow_up advice_did_not_work) / Worse (follow_up crop_or_animal_damaged)
  q3 only if the action needs buying an input or extra work: "If not, what stopped you?" -> Too costly / Not available nearby (follow_up could_not_get_input) / No time / Did not understand
- do_not_act:
  q1 survey-confirm "Did you <not do the thing the farmer was told not to do, named concretely>?" -> Yes / No
  q2 survey-single-select "How is the <problem the farmer asked about> in your <crop or animal> now?" -> Better / Same (follow_up advice_did_not_work) / Worse (follow_up crop_or_animal_damaged)
- plan_created:
  q1 survey-single-select "How much of the plan for <the problem> have you done?" -> All steps / Some steps / Not started
  q2 survey-single-select "Is the plan working for <the problem> so far?" -> Yes / Too early to say / No (follow_up advice_did_not_work)
- wait_and_monitor: the farmer was told to watch a specific sign before acting. Check both the watching and the outcome.
  q1 survey-single-select "Since we spoke, have you seen <the specific sign> on your <crop or animal>?" -> Yes (follow_up advice_did_not_work) / No / Did not check
  q2 survey-single-select "Is the <problem> in your <crop or animal> under control, or do you need more help?" -> Under control / Need more help (follow_up advice_did_not_work) / Not sure yet
  Never ask a bare "Do you need more help?": it must name the problem and give the "under control" answer.
- escalate_to_expert:
  q1 survey-single-select "Did you <meet or call the advised expert> about <the problem>?" -> Yes / Not yet / Could not reach (follow_up could_not_reach_expert)
  q2 survey-single-select "Did their advice help with <the problem>?" -> Yes / No (follow_up advice_did_not_work) / Not met yet
Name things the way the insight does. Never write "the advised stage", "the advised dose" or "as advised" on its own:
say what it is if the insight says it; if the insight does not name it, describe the action itself
(for example "Did you wait to give the first irrigation, instead of giving it early?").
The outcome question is about the crop or animal the farmer cares about (for fodder advice, ask about the animal).
Write plain, natural sentences a farmer would say out loud, in English and in Hindi."""

HINDI_STYLE_V3 = """

For hi-IN surveys:
- Use simple, everyday spoken Hindi as farmers in Bihar talk. Short sentences, common village words.
- Avoid formal, written or Sanskritized words. Prefer बीमारी over व्याधि, दवा over कीटनाशक when the farmer would say दवा,
  पानी देना over सिंचाई करना, देखा over अवलोकन किया, ठीक over स्वस्थ, कीड़े over कीट.
- Do not translate English word by word. Say it the way a farmer would. Write "क्या आपने खेत में कच्चा गोबर नहीं डाला?",
  not "क्या आपने कच्चा गोबर डालने से खुद को रोका?".
- Answer labels are short, natural replies a farmer would tap, for example हाँ, नहीं, अभी नहीं, पहले से ठीक, पहले जैसा,
  पहले से खराब, देखा नहीं. Each label is at most 20 characters including spaces and matras; count them.
- Use local crop and pest words: माहू (aphid), झुलसा (blight), गोफ (maize whorl), दीमक (termite)."""

# Prompt v4: v2 with only these changes (v3 changed outcome questions too, which lowered the
# golden-set match with Digital Green's reference questions):
# 1. wait_and_monitor q2 names the problem and offers "Under control"; a bare "Do you need more help?" is not allowed.
# 2. Action and sign questions name the action, sign or problem; "the advised stage" or "as advised" is not allowed.
# 3. Outcome questions keep the v2 wording and answer choices.
# 4. Hindi: the v3 instructions, plus the right term for animal-health and artificial-insemination workers.
PATTERNS_V4 = """

Use Digital Green's standard MEL question patterns. Fill in the specific action, sign, crop or animal from the
insight in short plain words. Keep these answer sets (translated for hi-IN) so answers can be compared across farmers:
- direct_action:
  q1 survey-single-select "Did you <do the advised action, named concretely>?" -> Yes / Not yet / No
  q2 survey-single-select "How is your <crop or animal> now?" -> Better / Same (follow_up advice_did_not_work) / Worse (follow_up crop_or_animal_damaged)
  q3 only if the action needs buying an input or extra work: "If not, what stopped you?" -> Too costly / Not available nearby (follow_up could_not_get_input) / No time / Did not understand
- do_not_act:
  q1 survey-confirm "Did you <not do the thing the farmer was told not to do, named concretely>?" -> Yes / No
  q2 survey-single-select "How is your <crop or animal> now?" -> Better / Same (follow_up advice_did_not_work) / Worse (follow_up crop_or_animal_damaged)
- plan_created:
  q1 survey-single-select "How much of the plan for <the problem> have you done?" -> All steps / Some steps / Not started
  q2 survey-single-select "Is the plan working so far?" -> Yes / Too early to say / No (follow_up advice_did_not_work)
- wait_and_monitor:
  q1 survey-single-select "Have you seen <the specific sign the farmer was told to watch for>?" -> Yes (follow_up advice_did_not_work) / No / Did not check
  q2 survey-single-select "Is the <problem> in your <crop or animal> under control, or do you need more help?" -> Under control / Need more help (follow_up advice_did_not_work) / Not sure yet
  Never ask a bare "Do you need more help?": q2 must name the problem and offer the "Under control" answer.
- escalate_to_expert:
  q1 survey-single-select "Did you <meet or call the advised expert, named concretely> about <the problem>?" -> Yes / Not yet / Could not reach (follow_up could_not_reach_expert)
  q2 survey-single-select "Did their advice help?" -> Yes / No (follow_up advice_did_not_work) / Not met yet
Questions about an action or a sign must name the action, sign or problem from the insight. Never write
"the advised stage", "the advised dose", "as advised" or similar on their own: say what it is if the insight says it;
if the insight does not name it, describe the action itself (for example "Did you wait to give the first irrigation,
instead of giving it early?").
Outcome questions keep the wording above, "How is your <crop or animal> now?", with Better / Same / Worse.
The outcome question is about the crop or animal the farmer cares about (for fodder advice, ask about the animal)."""

HINDI_STYLE_V4 = HINDI_STYLE_V3 + """
- Use the right word for the person the farmer was sent to. Artificial insemination worker: गाभिन कराने वाले
  (or कृत्रिम गर्भाधान वाले if needed). Community animal-health worker: पशु सखी or पशु मित्र. Vet: पशु डॉक्टर.
  Never call them टीका लगाने वाले (vaccinator) unless the advice was about vaccination."""

PROMPT_VERSIONS = ("v1", "v2", "v3", "v4")
PROMPT_VERSION = os.getenv("MEL_PROMPT_VERSION", "v2")
if PROMPT_VERSION not in PROMPT_VERSIONS:
    raise ValueError(f"MEL_PROMPT_VERSION must be one of {PROMPT_VERSIONS}, not {PROMPT_VERSION!r}")


def _examples(language):
    lang = "hi-IN" if language == "hi-IN" else "en-IN"
    out = []
    for ex in data.scenario_examples():
        ins = {k: ex["insight"][k] for k in ("asset", "concern", "severity", "query_summary", "advice_summary",
                                             "resolution_type", "action_window_days", "verification")}
        survey = {"rationale": ex[lang]["rationale"], "items": ex[lang]["items"]}
        out.append(f"Insight: {json.dumps(ins, ensure_ascii=False)}\nSurvey ({lang}): {json.dumps(survey, ensure_ascii=False)}")
    return "\n\n".join(out)


def _system():
    asks = "\n".join(f"- {k}: {v['asks']}" for k, v in data.rules()["survey_by_resolution"].items() if v["survey"])
    patterns = {"v1": "", "v2": PATTERNS, "v3": PATTERNS_V3 + HINDI_STYLE_V3,
                "v4": PATTERNS_V4 + HINDI_STYLE_V4}[PROMPT_VERSION]
    return SYSTEM.format(asks=asks, patterns=patterns)


def write(insight, language, usage, feedback=None):
    """Returns the model's draft: {"skip", "skip_reason", "rationale", "items"}."""
    fields = {k: insight.get(k) for k in ("asset", "concern", "behavioral_intent", "severity", "query_summary",
                                          "advice_summary", "resolution_type", "action_window_days", "verification")}
    user = (f"Worked examples from Digital Green:\n\n{_examples(language)}\n\n---\n"
            f"Survey language: {language}\n"
            f"Insight: {json.dumps(fields, ensure_ascii=False)}\n")
    if language not in ("en-IN", "hi-IN"):
        user += f"The examples are in another language; write prompts and labels in {language}.\n"
    if feedback:
        user += f"\nYour previous draft failed these checks. Fix them:\n- " + "\n- ".join(feedback) + "\n"
    user += "\nCall write_survey with the survey."
    return llm.call_tool(config.WRITER_MODEL, _system(), user, "write_survey",
                         "Return the follow-up survey for this insight.", TOOL_SCHEMA, usage, max_tokens=3000)
