"""JaakEngine: five operations over immutable session states (Req 20.3).

Commit-on-success: every operation computes the new state first and stores it
only when nothing raised, so an error leaves the session unchanged (Req 20.7).
Happy path only: failure events, not-now/opt-out and timeouts arrive with the
session transitions of tasks 10.2, 11.1 and 12.1.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Union

from . import boundary, record, session
from .errors import (
    GreetingFailed,
    InvalidRequest,
    NotEnded,
    OutOfOrder,
    RecordInvalid,
    RecordUnavailable,
    SessionFinalised,
    SurveyTextMissing,
    TurnsPending,
    UnknownSession,
)
from .logs import LogSink, NullLogSink
from .models import (
    AnswerReceipt,
    CallTimes,
    ClosingNotDelivered,
    ReportFailure,
    Timeout,
    Turn,
)
from .templates import TemplateSet

__all__ = ["JaakEngine", "CallerEvent"]

CallerEvent = Union[Timeout, ReportFailure, ClosingNotDelivered]
LANGUAGES = ("hi-IN", "en-IN")


@dataclass
class _Entry:
    """Engine-side holder for one session; ``state`` is replaced, never mutated."""

    state: session.SessionState
    delivery_attempt: int
    call_times: Optional[CallTimes]
    record: Optional[dict] = None
    finalised: bool = False
    record_failed: bool = False


class JaakEngine:
    """Text-only survey dialogue engine. Construction is not an operation."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        log: Optional[LogSink] = None,
        name_copy_path: Optional[Path] = None,
        id_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        self._clock = clock
        self._log: LogSink = log if log is not None else NullLogSink()
        # Stored only. The Farmer_Name_Copy is read and used from task 13.1.
        self._name_copy_path = name_copy_path
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        # Fail fast: any template problem raises here and no session can start (Req 7.7).
        self._templates = {lang: TemplateSet.load(lang) for lang in LANGUAGES}
        self._sessions: dict[str, _Entry] = {}

    # ------------------------------------------------------------------ helpers
    def _entry(self, session_id: str, *, allow_finalised: bool = False) -> _Entry:
        entry = self._sessions.get(session_id) if isinstance(session_id, str) else None
        if entry is None:
            raise UnknownSession("unknown session")
        if entry.finalised and not allow_finalised:
            raise SessionFinalised("session finalised")
        return entry

    def _ctx(self, state: session.SessionState) -> session.StepContext:
        return session.StepContext(self._templates[state.survey.language])

    # --------------------------------------------------------------- operations
    def start_session(
        self,
        survey: dict,
        farmer: dict,
        *,
        delivery_attempt: int = 1,
        call_times: Optional[CallTimes] = None,
    ) -> str:
        attempt = boundary.require_delivery_attempt(delivery_attempt, self._log)
        if call_times is not None and not isinstance(call_times, CallTimes):
            raise InvalidRequest(boundary="call_parameters", failures=[("/call_times", "type")])
        result = boundary.validate_inputs(survey, farmer, self._log)
        survey_model, farmer_model = result.model
        try:
            state = session.initial_state(survey_model)
            state, _ = session.step(state, session.StartInput(), self._ctx(state))
        except SurveyTextMissing as exc:
            raise GreetingFailed("greeting could not be rendered") from exc
        boundary.detect_language_mismatch(survey_model, farmer_model, self._log)
        session_id = self._id_factory()
        self._sessions[session_id] = _Entry(state, attempt, call_times)
        return session_id

    def next_turn(self, session_id: str) -> Optional[Turn]:
        entry = self._entry(session_id)
        new_state, turn = session.pop_turn(entry.state)
        entry.state = new_state
        return turn

    def submit_answer(
        self, session_id: str, text: str, *, utterance_complete: bool
    ) -> AnswerReceipt:
        entry = self._entry(session_id)
        if utterance_complete is not True:
            return AnswerReceipt.IGNORED  # Req 5.8, 5.9: no state change
        text = boundary.require_transcribed_answer(text, self._log)
        state = entry.state
        if state.queue:
            raise OutOfOrder("Turns are pending")
        if state.end is not None or state.phase not in (
            session.PHASE_AWAIT_GREETING_REPLY,
            session.PHASE_AWAIT_ITEM,
        ):
            raise OutOfOrder("no reply is awaited")
        new_state, _ = session.step(
            state, session.AnswerInput(text, self._clock()), self._ctx(state)
        )
        entry.state = new_state
        return AnswerReceipt.PROCESSED

    def submit_event(self, session_id: str, event: CallerEvent) -> None:
        entry = self._entry(session_id)
        if isinstance(event, Timeout):
            state = entry.state
            if state.queue:
                raise OutOfOrder("Turns are pending")
            if state.end is not None or state.phase not in (
                session.PHASE_AWAIT_GREETING_REPLY,
                session.PHASE_AWAIT_ITEM,
            ):
                raise OutOfOrder("no reply is awaited")
            # session.step raises NotImplementedError until task 10.2.
            new_state, _ = session.step(state, session.TimeoutInput(), self._ctx(state))
            entry.state = new_state
            return None
        if isinstance(event, (ReportFailure, ClosingNotDelivered)):
            raise NotImplementedError(
                f"{type(event).__name__} is not supported yet (tasks 11.1 and 16)"
            )
        raise InvalidRequest(boundary="caller_event_input", failures=[("/event", "type")])

    def get_response(self, session_id: str) -> dict:
        entry = self._entry(session_id, allow_finalised=True)
        if entry.record is not None:
            return entry.record
        if entry.record_failed:
            raise RecordUnavailable("no Response_Record is available")
        state = entry.state
        if state.end is None:
            raise NotEnded("session has not ended")
        if state.queue:
            raise TurnsPending("Turns are pending")
        try:
            built = record.build_record(
                state.survey,
                session.item_outcomes(state),
                delivery_attempt=entry.delivery_attempt,
                recorded_at=self._clock(),
                log=self._log,
                answered_at=state.answered_at,
                call_times=entry.call_times,
            )
        except RecordInvalid:
            entry.record_failed = True  # later calls raise RecordUnavailable
            raise
        entry.record = built
        entry.finalised = True
        return built
