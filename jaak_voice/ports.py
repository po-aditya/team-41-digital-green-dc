"""Ports: every external dependency of the voice layer sits behind one of these interfaces."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

EVENT_TIMEOUT = "timeout"
EVENT_CALL_DROPPED = "call_dropped"


class EngineError(Exception):
    """The dialogue engine rejected a call. Messages never contain farmer text."""


class EventUnsupported(EngineError):
    """The engine does not (yet) support this caller event."""


@dataclass(frozen=True)
class Utterance:
    """One thing the agent says, in engine-neutral form."""

    text: str
    kind: str                      # greeting, question, reask, repeat, advice_decline, reprompt, closing
    expects_reply: bool
    item_id: Optional[str] = None
    prompt: Optional[str] = None   # the survey question text, when the turn carries one
    options: tuple = ()            # option labels, in order, when the turn lists them


@runtime_checkable
class DialogueEngine(Protocol):
    """Five operations: start, next turn, submit answer, submit event, get response."""

    def start_session(self, survey: dict, farmer: dict) -> str: ...
    def next_turn(self, session_id: str) -> Optional[Utterance]: ...
    def submit_answer(self, session_id: str, text: str, *, utterance_complete: bool = True) -> bool: ...
    def submit_event(self, session_id: str, event: str) -> None: ...   # EVENT_TIMEOUT | EVENT_CALL_DROPPED
    def get_response(self, session_id: str) -> dict: ...


@runtime_checkable
class AgentAdapter(Protocol):
    """Source of Surveys and Farmer_Records, sink for Response_Records."""

    def list_scenarios(self) -> list: ...
    def get_survey(self, survey_id: str, language: Optional[str] = None) -> dict: ...
    def get_farmer(self, farmer_id: str) -> dict: ...
    def submit_response(self, response_record: dict) -> str: ...
    def validate_response(self, response_record: dict) -> list: ...   # [] when valid


@runtime_checkable
class SpeechToText(Protocol):
    def transcribe(self, audio_bytes: bytes, language: str) -> str: ...


@runtime_checkable
class TextToSpeech(Protocol):
    def synthesize(self, text: str, language: str) -> bytes: ...
