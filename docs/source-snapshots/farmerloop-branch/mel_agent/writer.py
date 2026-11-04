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
PROMPT_VERSION = os.getenv("MEL_PROMPT_VERSION", "v2")


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
    return SYSTEM.format(asks=asks, patterns=PATTERNS if PROMPT_VERSION == "v2" else "")


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
