"""JaakEngineAdapter: the only module that touches the text-only engine package."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from mel_agent.jaak import JaakEngine, JaakError, ReportFailure, Timeout, Turn

from .ports import EVENT_CALL_DROPPED, EVENT_TIMEOUT, EngineError, EventUnsupported, Utterance

_IST = timezone(timedelta(hours=5, minutes=30))


def _now() -> datetime:
    return datetime.now(_IST)


def _to_utterance(turn: Turn) -> Utterance:
    prompt = next((s.text for s in turn.segments if s.source == "survey_prompt"), None)
    options = tuple(s.text for s in turn.segments if s.source == "option_label")
    return Utterance(text=turn.text, kind=turn.kind, expects_reply=turn.expects_reply,
                     item_id=turn.item_id, prompt=prompt, options=options)


class JaakEngineAdapter:
    """DialogueEngine implementation over JaakEngine (start_session, next_turn, submit_answer,
    submit_event, get_response)."""

    def __init__(self, clock: Optional[Callable[[], datetime]] = None) -> None:
        self._engine = JaakEngine(clock=clock or _now)

    def start_session(self, survey: dict, farmer: dict) -> str:
        try:
            return self._engine.start_session(survey, farmer)
        except JaakError as exc:
            raise EngineError(f"{type(exc).__name__}: {exc}") from None

    def next_turn(self, session_id: str) -> Optional[Utterance]:
        try:
            turn = self._engine.next_turn(session_id)
        except JaakError as exc:
            raise EngineError(type(exc).__name__) from None
        return None if turn is None else _to_utterance(turn)

    def submit_answer(self, session_id: str, text: str, *, utterance_complete: bool = True) -> bool:
        try:
            receipt = self._engine.submit_answer(session_id, text, utterance_complete=utterance_complete)
        except JaakError as exc:
            raise EngineError(type(exc).__name__) from None
        return receipt.value == "processed"

    def submit_event(self, session_id: str, event: str) -> None:
        if event == EVENT_TIMEOUT:
            ev = Timeout()
        elif event == EVENT_CALL_DROPPED:
            ev = ReportFailure(failure_code="voice_call_dropped")
        else:
            raise EngineError(f"unknown event {event!r}")
        try:
            self._engine.submit_event(session_id, ev)
        except NotImplementedError:
            raise EventUnsupported(f"{event} is not supported by the engine yet") from None
        except JaakError as exc:
            raise EngineError(type(exc).__name__) from None

    def get_response(self, session_id: str) -> dict:
        try:
            return self._engine.get_response(session_id)
        except JaakError as exc:
            raise EngineError(type(exc).__name__) from None
