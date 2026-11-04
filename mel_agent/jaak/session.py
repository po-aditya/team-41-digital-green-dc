"""Dialogue session state machine, happy path plus re-ask (Req 2.1, 5, 10, 14.1).

``step(state, input, ctx) -> (state', turns)`` is pure: it never mutates
``state`` and returns a new frozen ``SessionState``. The engine commits the new
state only if ``step`` returns normally (commit-on-success).

Queue handling
--------------
Turns produced by a step are appended to ``state.queue`` (and also returned).
The engine hands them out in order with ``pop_turn(state)``, which removes the
head and applies the "Turn taken" phase change (``greeting`` becomes
``await_greeting_reply``; a taken closing Turn moves ``closing`` to ``ended``).

Phases
------
``greeting`` -> ``await_greeting_reply`` -> ``await_item`` (one Item at a time)
-> ``closing`` (``end`` set, closing Turn queued) -> ``ended``.

Not yet implemented (raise ``NotImplementedError``): timeout (10.2), not-now,
opt-out, skip (11.1), caller failure and advice/ambiguous (12.1).

Privacy: unclear text is never copied into state. Only the accepted attempt's
text is kept, truncated to 256 characters.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Optional, Union

from . import classify as cl
from . import outcome, render
from .classify import UtteranceClass
from .errors import OutOfOrder
from .models import Survey, Turn
from .templates import TemplateSet

__all__ = [
    "RAW_TEXT_MAX",
    "END_ALL_RESOLVED",
    "ItemState",
    "SessionState",
    "StepContext",
    "StartInput",
    "AnswerInput",
    "TimeoutInput",
    "NotNowInput",
    "OptOutInput",
    "FailureInput",
    "StepInput",
    "initial_state",
    "step",
    "pop_turn",
    "item_outcomes",
]

RAW_TEXT_MAX = 256
END_ALL_RESOLVED = "all_resolved"

PHASE_GREETING = "greeting"
PHASE_AWAIT_GREETING_REPLY = "await_greeting_reply"
PHASE_AWAIT_ITEM = "await_item"
PHASE_CLOSING = "closing"
PHASE_ENDED = "ended"


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ItemState:
    attempts: int = 0          # question + reask Turns queued (0 to 2)
    repeats: int = 0           # advice/reprompt repeats (task 12.1)
    result: str = "not_reached"  # pending | answered | skipped | invalid | not_reached
    value: Optional[Union[str, int]] = None
    accepted_text: Optional[str] = None  # only for an answered Item, max 256
    skip_by_request: bool = False
    timeouts: int = 0


@dataclass(frozen=True)
class SessionState:
    survey: Survey
    phase: str
    item_index: int
    items: tuple[ItemState, ...]
    queue: tuple[Turn, ...] = ()
    end: Optional[str] = None            # end reason, None while running
    answered_at: Optional[datetime] = None  # clock at the last accepted answer
    closing_required: bool = False
    closing_delivered: bool = False

    @property
    def ended(self) -> bool:
        """True once the session has an end reason (closing Turn may still be queued)."""
        return self.end is not None


@dataclass(frozen=True)
class StepContext:
    templates: TemplateSet


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StartInput:
    """Queue the greeting. ``farmer_name`` is for task 13.1 (name copy); None means plain."""
    farmer_name: Optional[str] = None


@dataclass(frozen=True)
class AnswerInput:
    text: str
    at: datetime


@dataclass(frozen=True)
class TimeoutInput:
    """Task 10.2."""


@dataclass(frozen=True)
class NotNowInput:
    """Task 11.1."""


@dataclass(frozen=True)
class OptOutInput:
    """Task 11.1."""


@dataclass(frozen=True)
class FailureInput:
    """Caller-reported failure, task 11.1 / 12.1."""
    code: str = ""


StepInput = Union[StartInput, AnswerInput, TimeoutInput, NotNowInput, OptOutInput, FailureInput]


# --------------------------------------------------------------------------- #
# Construction and views
# --------------------------------------------------------------------------- #
def initial_state(survey: Survey) -> SessionState:
    """State before ``StartInput``: phase ``greeting``, nothing queued."""
    return SessionState(
        survey=survey,
        phase=PHASE_GREETING,
        item_index=0,
        items=tuple(ItemState() for _ in survey.items),
    )


def item_outcomes(state: SessionState) -> list[outcome.ItemOutcome]:
    """One ``ItemOutcome`` per Survey Item in order; unreached Items have attempts 0."""
    out: list[outcome.ItemOutcome] = []
    for item, st in zip(state.survey.items, state.items):
        if st.result == "answered":
            out.append(outcome.ItemOutcome(item.item_id, "answered", st.value, st.attempts,
                                           st.accepted_text))
        elif st.result in ("skipped", "invalid"):
            out.append(outcome.ItemOutcome(item.item_id, st.result, None, st.attempts, None))
        else:  # pending (shown, unresolved) or not_reached
            if st.attempts == 0:
                out.append(outcome.ItemOutcome(item.item_id, "not_reached", None, 0, None))
            else:
                out.append(outcome.ItemOutcome(item.item_id, "skipped", None, st.attempts, None))
    return out


def pop_turn(state: SessionState) -> tuple[SessionState, Optional[Turn]]:
    """Hand out the head Turn and apply the "Turn taken" phase change."""
    if not state.queue:
        return state, None
    turn, rest = state.queue[0], state.queue[1:]
    new = replace(state, queue=rest)
    if turn.kind == "greeting" and state.phase == PHASE_GREETING:
        new = replace(new, phase=PHASE_AWAIT_GREETING_REPLY)
    elif turn.kind == "closing":
        new = replace(new, closing_delivered=True,
                      phase=PHASE_ENDED if not rest else new.phase)
    return new, turn


# --------------------------------------------------------------------------- #
# Transitions
# --------------------------------------------------------------------------- #
def _set_item(items: tuple[ItemState, ...], index: int, item_state: ItemState) -> tuple[ItemState, ...]:
    return items[:index] + (item_state,) + items[index + 1:]


def _ask_item(state: SessionState, index: int, ctx: StepContext) -> tuple[SessionState, Turn]:
    """Queue the first ask of Item ``index`` (attempts 1)."""
    item = state.survey.items[index]
    turn = render.render_question(item, ctx.templates, state.survey.language)
    items = _set_item(state.items, index, ItemState(attempts=1, result="pending"))
    return replace(state, item_index=index, items=items, phase=PHASE_AWAIT_ITEM,
                   queue=state.queue + (turn,)), turn


def _advance(state: SessionState, ctx: StepContext) -> tuple[SessionState, tuple[Turn, ...]]:
    """Next Item or closing after the current Item resolved."""
    nxt = state.item_index + 1
    if nxt < len(state.survey.items):
        new, turn = _ask_item(state, nxt, ctx)
        return new, (turn,)
    closing = render.render_closing(ctx.templates, "done", state.survey.language)
    new = replace(state, phase=PHASE_CLOSING, end=END_ALL_RESOLVED, closing_required=True,
                  queue=state.queue + (closing,))
    return new, (closing,)


def _start(state: SessionState, inp: StartInput, ctx: StepContext) -> tuple[SessionState, tuple[Turn, ...]]:
    if state.phase != PHASE_GREETING or state.queue or state.end is not None:
        raise OutOfOrder("session already started")
    turn = render.render_greeting(ctx.templates, state.survey.language, inp.farmer_name)
    return replace(state, queue=(turn,)), (turn,)


def _greeting_reply(state: SessionState, inp: AnswerInput,
                    ctx: StepContext) -> tuple[SessionState, tuple[Turn, ...]]:
    res = cl.classify(inp.text, cl.greeting_reply())
    if res.cls not in (UtteranceClass.ANSWER, UtteranceClass.UNCLEAR,
                       UtteranceClass.UNCLEAR_REDACTED):
        raise NotImplementedError(
            f"greeting reply class {res.cls.value}: not-now/opt-out handling arrives in task 11.1"
        )
    # Any non-phrase reply: text discarded, not stored, not an attempt (Req 5.10, 5.11).
    new, turn = _ask_item(state, 0, ctx)
    return new, (turn,)


def _item_answer(state: SessionState, inp: AnswerInput,
                 ctx: StepContext) -> tuple[SessionState, tuple[Turn, ...]]:
    idx = state.item_index
    item = state.survey.items[idx]
    cur = state.items[idx]
    res = cl.classify(inp.text, cl.item_answer(item, state.survey.language))

    if res.cls is UtteranceClass.ANSWER:
        done = replace(cur, result="answered", value=res.value,
                       accepted_text=inp.text[:RAW_TEXT_MAX])
        new = replace(state, items=_set_item(state.items, idx, done), answered_at=inp.at)
        return _advance(new, ctx)

    if res.cls in (UtteranceClass.UNCLEAR, UtteranceClass.UNCLEAR_REDACTED):
        if cur.attempts < 2:
            turn = render.render_reask(item, ctx.templates, state.survey.language)
            nxt = replace(cur, attempts=2)
            new = replace(state, items=_set_item(state.items, idx, nxt),
                          queue=state.queue + (turn,))
            return new, (turn,)
        bad = replace(cur, result="invalid", value=None, accepted_text=None, attempts=2)
        new = replace(state, items=_set_item(state.items, idx, bad))
        return _advance(new, ctx)

    raise NotImplementedError(
        f"utterance class {res.cls.value}: skip/not-now/opt-out arrive in task 11.1, "
        "advice/ambiguous in task 12.1"
    )


def step(state: SessionState, inp: StepInput,
         ctx: StepContext) -> tuple[SessionState, tuple[Turn, ...]]:
    """Apply one input. Returns ``(new_state, turns_queued_by_this_step)``."""
    if isinstance(inp, TimeoutInput):
        raise NotImplementedError("timeout transitions arrive in task 10.2")
    if isinstance(inp, (NotNowInput, OptOutInput)):
        raise NotImplementedError("not-now and opt-out transitions arrive in task 11.1")
    if isinstance(inp, FailureInput):
        raise NotImplementedError("caller-failure transitions arrive in tasks 11.1 and 12.1")
    if isinstance(inp, StartInput):
        return _start(state, inp, ctx)
    if isinstance(inp, AnswerInput):
        if state.end is not None or state.phase in (PHASE_CLOSING, PHASE_ENDED):
            raise OutOfOrder("session has ended")
        if state.phase == PHASE_AWAIT_GREETING_REPLY:
            return _greeting_reply(state, inp, ctx)
        if state.phase == PHASE_AWAIT_ITEM:
            return _item_answer(state, inp, ctx)
        raise OutOfOrder(f"no reply expected in phase {state.phase}")
    raise TypeError(f"unknown step input {type(inp).__name__}")
