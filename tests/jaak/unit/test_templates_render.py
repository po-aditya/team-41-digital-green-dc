"""Unit tests for the fixed template sets and the Turn renderer (task 3.4).

Covers Req 2.2, 3.6, 4.4, 5.6, 5.7, 6.1, 6.2, 6.3, 6.7, 6.8, 7.1 to 7.7, 14.3, 17.1.
"""
from __future__ import annotations

import copy
import json
import re

import pytest

from mel_agent.jaak import render
from mel_agent.jaak.errors import LanguageUnavailable, SurveyTextMissing, TemplateError
from mel_agent.jaak.models import Item, Option
from mel_agent.jaak.templates import (
    COMPOSITIONS,
    REQUIRED_TEMPLATES,
    TEMPLATE_DIR,
    TemplateSet,
    split_sentences,
)

LANGS = ("en-IN", "hi-IN")
NAMED = "Anil Kumar Singh"


def _raw(lang: str) -> dict:
    return json.loads((TEMPLATE_DIR / f"{lang}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module", params=LANGS)
def lang(request) -> str:
    return request.param


@pytest.fixture(scope="module")
def tset(lang) -> TemplateSet:
    return TemplateSet.load(lang)


def _select(options, item_type="survey-single-select", prompt="Prompt?") -> Item:
    return Item.model_validate({
        "item_id": "q_one", "type": item_type, "prompt": prompt,
        "options": [{"value": v, "label": lbl} for v, lbl in options],
    })


def _scale(lo=0, hi=10) -> Item:
    return Item.model_validate({
        "item_id": "q_scale", "type": "survey-scale", "prompt": "Rate it",
        "scale_min": lo, "scale_max": hi,
    })


COLOURS = [("red", "Red"), ("green", "Green"), ("blue", "Blue")]


def _all_turns(ts: TemplateSet) -> list:
    sel = _select(COLOURS)
    conf = _select([("yes", "Yes"), ("no", "No")], "survey-confirm")
    sc = _scale(0, 10)
    turns = [render.render_greeting(ts), render.render_greeting(ts, farmer_name=NAMED)]
    for it in (sel, conf, sc):
        turns += [render.render_question(it, ts), render.render_reask(it, ts),
                  render.render_repeat(it, ts), render.render_advice_decline(it, ts),
                  render.render_reprompt(it, ts)]
    turns += [render.render_closing(ts, v) for v in ("done", "declined", "opted_out")]
    return turns


# --------------------------------------------------------------------------- #
# Shipped sets
# --------------------------------------------------------------------------- #


def test_shipped_sets_load_with_all_templates(tset, lang):
    assert tset.language == lang
    assert set(tset.ids()) == set(REQUIRED_TEMPLATES)


def test_unavailable_language_raises():
    with pytest.raises(LanguageUnavailable):
        TemplateSet.load("fr-IN")


def test_greeting_content(tset, lang):
    t = render.render_greeting(tset)
    assert t.kind == "greeting" and t.expects_reply
    assert "JAAK" in t.text
    assert "FarmerChat" in t.text if lang == "en-IN" else "फार्मरचैट" in t.text
    assert ("survey" in t.text) if lang == "en-IN" else ("सर्वे" in t.text)
    assert len(split_sentences(t.text)) <= 2
    assert t.text.rstrip().endswith("?")
    # the question is the "good time" question: last sentence is its own question
    assert split_sentences(t.text)[-1].endswith("?")


def test_no_template_asks_name_or_offers_language(tset, lang):
    banned = {
        "en-IN": ("name", "language", "english", "hindi"),
        "hi-IN": ("नाम", "भाषा", "हिंदी", "हिन्दी", "अंग्रेज"),
    }[lang]
    for tid in tset.ids():
        text = re.sub(r"\{[a-z_]+\}", "", tset.text(tid)).casefold()
        for word in banned:
            assert word not in text, (tid, word)
    # the only template carrying a name slot is the named greeting
    holders = [t for t in tset.ids() if "{farmer_name}" in tset.text(t)]
    assert holders == ["greeting_named"]


def test_closings_end_with_thanks_and_no_question(tset, lang):
    thanks = {"en-IN": ("thank",), "hi-IN": ("धन्यवाद", "शुक्रिया")}[lang]
    for variant in ("done", "declined", "opted_out"):
        t = render.render_closing(tset, variant)
        assert t.kind == "closing" and not t.expects_reply
        assert "?" not in t.text
        last = split_sentences(t.text)[-1].casefold()
        assert any(w in last for w in thanks)


def test_every_template_obeys_plain_text_rules(tset):
    for tid in tset.ids():
        text = tset.text(tid)
        assert len(text) <= 200
        assert not re.search(r"[*#`>|_~\[\]]|https?://|www\.", re.sub(r"\{[a-z_]+\}", "", text))
        for s in split_sentences(re.sub(r"\{[a-z_]+\}", "X", text)):
            assert len(s.split()) <= 20


def test_no_template_has_double_spaces(tset):
    for tid in tset.ids():
        assert "  " not in tset.text(tid)


# --------------------------------------------------------------------------- #
# Renderer
# --------------------------------------------------------------------------- #


def test_prompt_and_labels_copied_verbatim_with_whitespace_and_order(tset):
    prompt = "  Did  you\tuse it?\u00a0 "
    labels = ["  Zed ", "Alpha  beta", "मध्य\u200b"]
    item = _select([("a", labels[0]), ("b", labels[1]), ("c", labels[2])], prompt=prompt)
    for fn in (render.render_question, render.render_reask, render.render_repeat):
        t = fn(item, tset)
        prompts = [s for s in t.segments if s.source == "survey_prompt"]
        lbls = [s for s in t.segments if s.source == "option_label"]
        assert [s.text for s in prompts] == [prompt]
        assert [s.text for s in lbls] == labels  # character for character, order kept
        assert [s.ref for s in lbls] == [f"/items/q_one/options/{i}/label" for i in range(3)]
        assert prompts[0].ref == "/items/q_one/prompt"
        assert prompt in t.text
        pos = [t.text.index(label) for label in labels]
        assert pos == sorted(pos)


def test_scale_bounds_present(tset):
    for lo, hi in ((0, 10), (1, 5)):
        t = render.render_question(_scale(lo, hi), tset)
        tail = [s for s in t.segments if s.ref == "scale_tail"]
        assert len(tail) == 1 and str(lo) in tail[0].text and str(hi) in tail[0].text
        assert t.text.endswith(tail[0].text)
        assert "{" not in t.text


def test_question_turn_shapes(tset):
    t = render.render_question(_select(COLOURS), tset)
    assert t.kind == "question" and t.item_id == "q_one" and t.expects_reply
    assert t.text.rstrip().endswith("?")
    r = render.render_reask(_select(COLOURS), tset)
    assert r.kind == "reask" and r.segments[0].ref == "reask_prefix"
    assert render.render_repeat(_select(COLOURS), tset).kind == "repeat"


def test_no_double_spaces_in_any_turn(tset):
    for t in _all_turns(tset):
        assert "  " not in t.text, t.kind
        assert "".join(s.text for s in t.segments).count("  ") == 0


def test_text_only_from_allowed_sources(tset):
    for t in _all_turns(tset):
        assert {s.source for s in t.segments} <= {
            "survey_prompt", "option_label", "template", "farmer_name"}


def test_named_greeting_confines_name(tset):
    t = render.render_greeting(tset, farmer_name=NAMED)
    names = [s for s in t.segments if s.source == "farmer_name"]
    assert [s.text for s in names] == [NAMED]
    assert t.text.count(NAMED) == 1
    assert "JAAK" in t.text and t.text.rstrip().endswith("?")
    assert NAMED not in render.render_question(_select(COLOURS), tset).text


def test_worst_case_named_greeting_sentence_word_counts(tset, lang, capsys):
    t = render.render_greeting(tset, farmer_name=NAMED)
    counts = [len(s.split()) for s in split_sentences(t.text)]
    with capsys.disabled():
        print(f"\n[word counts] {lang} named greeting {counts}: {t.text}")
    assert counts and all(c <= 20 for c in counts), counts
    assert len(counts) <= 2


def test_empty_prompt_raises_without_output(tset):
    item = Item.model_construct(item_id="q_one", type="survey-single-select", prompt="",
                                options=[Option(value="a", label="A"), Option(value="b", label="B")])
    for fn in (render.render_question, render.render_reask, render.render_repeat):
        with pytest.raises(SurveyTextMissing):
            fn(item, tset)


def test_empty_or_blank_label_raises_without_output(tset):
    for bad in ("", "   "):
        item = Item.model_construct(
            item_id="q_one", type="survey-single-select", prompt="P?",
            options=[Option.model_construct(value="a", label=bad, follow_up=None),
                     Option(value="b", label="B")])
        for fn in (render.render_question, render.render_reask, render.render_repeat):
            with pytest.raises(SurveyTextMissing):
                fn(item, tset)


def test_missing_scale_bounds_raise(tset):
    item = Item.model_construct(item_id="q", type="survey-scale", prompt="P?",
                                scale_min=None, scale_max=None, options=None)
    with pytest.raises(SurveyTextMissing):
        render.render_question(item, tset)


def test_missing_language_raises_without_output(tset, lang):
    item = _select(COLOURS)
    other = "hi-IN" if lang == "en-IN" else "en-IN"
    for call in (
        lambda: render.render_question(item, None),
        lambda: render.render_greeting(None),
        lambda: render.render_closing(None),
        lambda: render.render_question(item, tset, other),
        lambda: render.render_greeting(tset, other),
    ):
        with pytest.raises(LanguageUnavailable):
            call()


def test_blank_farmer_name_raises(tset):
    with pytest.raises(SurveyTextMissing):
        render.render_greeting(tset, farmer_name="   ")


# --------------------------------------------------------------------------- #
# Load-time violations (from_dict on mutated copies of the shipped JSON)
# --------------------------------------------------------------------------- #


def _mutated(lang: str, tid: str, text: str | None = None, role: str | None = None) -> dict:
    raw = copy.deepcopy(_raw(lang))
    if text is not None:
        raw["templates"][tid]["text"] = text
    if role is not None:
        raw["templates"][tid]["role"] = role
    return raw


def test_unmutated_copy_loads(lang):
    assert TemplateSet.from_dict(lang, copy.deepcopy(_raw(lang))).language == lang


def _expect(lang: str, raw: dict, tid: str, rule: str) -> None:
    with pytest.raises(TemplateError) as ei:
        TemplateSet.from_dict(lang, raw)
    assert ei.value.rule == rule and ei.value.template_id == tid


def _long_words(n_words: int) -> str:
    return " ".join(["abcdefghijklmn"] * n_words)


def test_violation_rules(lang):
    q = "?" if lang == "en-IN" else "?"
    cases = [
        ("greeting_plain", "Hello *JAAK* is here. Is now a good time" + q, "markdown"),
        ("greeting_plain", "Hello JAAK \U0001F600 here. Is now a good time" + q, "emoji"),
        ("greeting_plain", "Hello JAAK see www.example.org now. Is it a good time" + q, "url"),
        ("greeting_plain", "Hello JAAK, survey_id here. Is it a good time" + q, "identifier"),
        ("reprompt", " ".join(["word"] * 21) + ".", "sentence_length"),
        ("reprompt", _long_words(14) + "?", "max_chars"),
        ("reprompt", "Sorry, I did not understand that.", "final_question_end"),
        ("closing_done", "Goodbye for now.", "closing_thanks"),
        ("closing_done", "Thank you for your time, goodbye?", "closing_question"),
        ("greeting_plain", "Hello {farmer_name} JAAK here. Is it a good time?", "placeholder"),
        ("option_tail", "Which one is {unknown}?", "placeholder"),
    ]
    for tid, text, rule in cases:
        text_used = text
        if lang == "hi-IN" and rule == "closing_thanks":
            text_used = "ठीक है।"
        if lang == "hi-IN" and rule == "closing_question":
            text_used = "आपका धन्यवाद?"
        if lang == "hi-IN" and rule == "final_question_end":
            text_used = "माफ़ कीजिए, बात समझ नहीं आई।"
        _expect(lang, _mutated(lang, tid, text=text_used), tid, rule)


def test_scale_tail_missing_slot_is_placeholder_violation(lang):
    _expect(lang, _mutated(lang, "scale_tail", text="Which number is it?"),
            "scale_tail", "placeholder")


def test_missing_unknown_and_role_mismatch(lang):
    raw = copy.deepcopy(_raw(lang))
    del raw["templates"]["reprompt"]
    _expect(lang, raw, "reprompt", "missing_template")

    raw = copy.deepcopy(_raw(lang))
    raw["templates"]["surprise"] = {"role": "final", "text": "Fine?"}
    _expect(lang, raw, "surprise", "unknown_template")

    _expect(lang, _mutated(lang, "reprompt", role="closing"), "reprompt", "role")
    _expect(lang, _mutated(lang, "closing_done", role="final"), "closing_done", "role")


def test_composition_sentence_count_violation(lang):
    tail = "Which one? Really? Sure? Tell me?"
    if lang == "hi-IN":
        tail = "कौन सा? सच में? पक्का? बताइए?"
    raw = _mutated(lang, "option_tail", text=tail)
    with pytest.raises(TemplateError) as ei:
        TemplateSet.from_dict(lang, raw)
    assert ei.value.rule == "sentence_count"
    assert ei.value.template_id.startswith("turn:")
    assert ei.value.template_id.split(":", 1)[1] in COMPOSITIONS


def test_invalid_file_shapes(lang):
    for bad in (None, [], {"language": lang}, {"language": "xx-XX", "templates": {}}):
        with pytest.raises(TemplateError) as ei:
            TemplateSet.from_dict(lang, bad)
        assert ei.value.rule == "invalid_file"


def test_nothing_returned_on_failure(lang):
    result = None
    with pytest.raises(TemplateError):
        result = TemplateSet.from_dict(lang, _mutated(lang, "closing_done", text="Goodbye."))
    assert result is None
