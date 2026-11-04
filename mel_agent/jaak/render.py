"""Turn renderer (Req 2, 5, 6, 10, 16, 18.5).

Every Turn is a list of segments, each tagged with one of four sources:
``survey_prompt``, ``option_label``, ``template`` and ``farmer_name``.
The renderer's parameters are the validated Survey ``Item``, the
``TemplateSet`` and (for the greeting) the farmer name. It has no parameter for
a Transcribed_Answer, an Insight, ``rationale``, ``state`` or ``district``.

Rendering is atomic: all checks run before any Turn is returned, so a failure
leaves the caller's state untouched (Req 6.7, 6.8).

Segment ``ref`` values:

* prompt: ``/items/{item_id}/prompt``
* label: ``/items/{item_id}/options/{index}/label``
* template: the template id
* farmer name: ``farmer_name``

Segments are joined with one space, except ``glue`` templates, which attach to
the left neighbour. Prompts and labels are copied verbatim.
"""
from __future__ import annotations

from typing import Optional

from .errors import LanguageUnavailable, SurveyTextMissing
from .models import Item, Segment, Turn
from .templates import TemplateSet

_NAME_PLACEHOLDER = "{farmer_name}"


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def assemble(segments: tuple[Segment, ...], glue_flags: tuple[bool, ...]) -> str:
    """Join with one space; glue attaches to the left neighbour.

    Glue templates such as ``" or "`` carry their own spacing, so no extra
    space is inserted after text that already ends in whitespace.
    """
    out = ""
    for seg, glue in zip(segments, glue_flags):
        if not out or glue or out[-1].isspace():
            out += seg.text
        else:
            out += " " + seg.text
    return out


class _Builder:
    def __init__(self, templates: TemplateSet) -> None:
        self.t = templates
        self.segs: list[Segment] = []
        self.glue: list[bool] = []

    def template(self, template_id: str, **values: object) -> None:
        tpl = self.t.get(template_id)
        self.segs.append(Segment(source="template", text=self.t.fill(template_id, **values),
                                 ref=template_id))
        self.glue.append(tpl.role == "glue")

    def literal(self, source: str, text: str, ref: str) -> None:
        self.segs.append(Segment(source=source, text=text, ref=ref))  # type: ignore[arg-type]
        self.glue.append(False)

    def turn(self, kind: str, item_id: Optional[str], expects_reply: bool) -> Turn:
        segs = tuple(self.segs)
        return Turn(kind=kind, language=self.t.language,  # type: ignore[arg-type]
                    text=assemble(segs, tuple(self.glue)), segments=segs,
                    item_id=item_id, expects_reply=expects_reply)


# --------------------------------------------------------------------------- #
# Checks (run before anything is built)
# --------------------------------------------------------------------------- #


def _check_language(templates: Optional[TemplateSet], language: Optional[str]) -> TemplateSet:
    if templates is None:
        raise LanguageUnavailable(language or "")
    if language is not None and templates.language != language:
        raise LanguageUnavailable(language)
    return templates


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _check_item(item: Item) -> None:
    if not _nonblank(item.prompt):
        raise SurveyTextMissing("prompt")
    if item.type == "survey-scale":
        if item.scale_min is None or item.scale_max is None:
            raise SurveyTextMissing("scale_bounds")
        return
    if not item.options:
        raise SurveyTextMissing("options")
    for opt in item.options:
        if not _nonblank(opt.label):
            raise SurveyTextMissing("label")


# --------------------------------------------------------------------------- #
# Question body shared by question / reask / repeat
# --------------------------------------------------------------------------- #


def _question_body(b: _Builder, item: Item) -> None:
    b.literal("survey_prompt", item.prompt, f"/items/{item.item_id}/prompt")
    if item.type == "survey-scale":
        b.template("scale_tail", scale_min=item.scale_min, scale_max=item.scale_max)
        return
    options = item.options or []
    n = len(options)
    b.template("option_lead_in")
    for i, opt in enumerate(options):
        if i > 0:
            b.template("option_sep_last" if i == n - 1 else "option_sep")
        b.literal("option_label", opt.label, f"/items/{item.item_id}/options/{i}/label")
    b.template("option_close")
    b.template("option_tail")


# --------------------------------------------------------------------------- #
# Public renderers
# --------------------------------------------------------------------------- #


def render_greeting(templates: TemplateSet, language: Optional[str] = None,
                    farmer_name: Optional[str] = None) -> Turn:
    """Greeting Turn. Plain unless ``farmer_name`` is given (name segment inside)."""
    templates = _check_language(templates, language)
    b = _Builder(templates)
    if farmer_name is None:
        b.template("greeting_plain")
    else:
        if not _nonblank(farmer_name):
            raise SurveyTextMissing("farmer_name")
        tpl = templates.get("greeting_named")
        before, _, after = tpl.text.partition(_NAME_PLACEHOLDER)
        # The greeting is one sentence flow; the name is its own segment and the
        # surrounding template text is glued so no extra spaces appear.
        if before:
            b.segs.append(Segment(source="template", text=before, ref="greeting_named"))
            b.glue.append(False)
        b.segs.append(Segment(source="farmer_name", text=farmer_name, ref="farmer_name"))
        b.glue.append(True)
        if after:
            b.segs.append(Segment(source="template", text=after, ref="greeting_named"))
            b.glue.append(True)
    return b.turn("greeting", None, True)


def _render_question(kind: str, item: Item, templates: TemplateSet,
                     language: Optional[str], reask: bool) -> Turn:
    templates = _check_language(templates, language)
    _check_item(item)
    b = _Builder(templates)
    if reask:
        b.template("reask_prefix")
    _question_body(b, item)
    return b.turn(kind, item.item_id, True)


def render_question(item: Item, templates: TemplateSet, language: Optional[str] = None) -> Turn:
    return _render_question("question", item, templates, language, reask=False)


def render_reask(item: Item, templates: TemplateSet, language: Optional[str] = None) -> Turn:
    return _render_question("reask", item, templates, language, reask=True)


def render_repeat(item: Item, templates: TemplateSet, language: Optional[str] = None) -> Turn:
    """The question content again, with kind ``repeat`` (after decline/reprompt)."""
    return _render_question("repeat", item, templates, language, reask=False)


def _render_single(kind: str, template_id: str, item_id: Optional[str], expects_reply: bool,
                   templates: TemplateSet, language: Optional[str]) -> Turn:
    templates = _check_language(templates, language)
    b = _Builder(templates)
    b.template(template_id)
    return b.turn(kind, item_id, expects_reply)


def render_advice_decline(item: Item, templates: TemplateSet,
                          language: Optional[str] = None) -> Turn:
    return _render_single("advice_decline", "advice_decline", item.item_id, True,
                          templates, language)


def render_reprompt(item: Item, templates: TemplateSet, language: Optional[str] = None) -> Turn:
    return _render_single("reprompt", "reprompt", item.item_id, True, templates, language)


_CLOSINGS = {
    "done": "closing_done",
    "declined": "closing_declined",
    "opted_out": "closing_opted_out",
}


def render_closing(templates: TemplateSet, variant: str = "done",
                   language: Optional[str] = None) -> Turn:
    """Closing Turn; ``variant`` is ``done``, ``declined`` or ``opted_out``. No reply expected."""
    if variant not in _CLOSINGS:
        raise ValueError("closing variant")
    return _render_single("closing", _CLOSINGS[variant], None, False, templates, language)
