"""CallSession: drives one call over the ports. No Streamlit, AWS or engine-package imports."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from .ports import (EVENT_CALL_DROPPED, EVENT_TIMEOUT, AgentAdapter, DialogueEngine, EngineError,
                    EventUnsupported, SpeechToText, TextToSpeech, Utterance)

ANSWER_PLACEHOLDER = "(answer received)"   # farmer words are never echoed back into the transcript


@dataclass(frozen=True)
class SpokenTurn:
    text: str
    audio: bytes
    utterance: Utterance


class CallSession:
    def __init__(self, engine: DialogueEngine, agent: AgentAdapter, stt: SpeechToText,
                 tts: TextToSpeech, clock: Callable[[], float] = time.perf_counter) -> None:
        self._engine, self._agent, self._stt, self._tts, self._clock = engine, agent, stt, tts, clock
        self._sid: Optional[str] = None
        self.language = "en-IN"
        self.transcript: list = []          # (speaker, text)
        self.notices: list = []
        self.latencies_ms: list = []
        self.ended = False
        self.current: Optional[Utterance] = None
        self._speech_end: Optional[float] = None
        self._result: Optional[dict] = None
        self._counts = {"advice_declined": 0, "unclear_answers": 0}

    # -- lifecycle -------------------------------------------------------
    def start(self, survey_id: str, farmer_id: str, language: Optional[str] = None) -> None:
        survey = self._agent.get_survey(survey_id, language)
        farmer = self._agent.get_farmer(farmer_id)
        self.language = survey["language"]
        self._sid = self._engine.start_session(survey, farmer)

    @property
    def awaiting_reply(self) -> bool:
        return bool(self.current and self.current.expects_reply and not self.ended)

    @property
    def last_latency_ms(self) -> Optional[float]:
        return self.latencies_ms[-1] if self.latencies_ms else None

    @property
    def counters(self) -> dict:
        """Derived only from the engine's public Turn kinds. Redaction and injection counters are
        left out because the engine exposes no signal for them."""
        return dict(self._counts)

    # -- agent side ------------------------------------------------------
    def next_turn(self) -> Optional[SpokenTurn]:
        u = self._engine.next_turn(self._sid)
        if u is None:
            return None
        audio = self._tts.synthesize(u.text, self.language)
        if self._speech_end is not None:
            self.latencies_ms.append((self._clock() - self._speech_end) * 1000.0)
            self._speech_end = None
        if u.kind == "advice_decline":
            self._counts["advice_declined"] += 1
        elif u.kind == "reask":
            self._counts["unclear_answers"] += 1
        if u.kind == "closing":
            self.ended = True
        self.current = u
        self.transcript.append(("jaak", u.text))
        return SpokenTurn(u.text, audio, u)

    # -- farmer side -----------------------------------------------------
    def handle_farmer_text(self, text: str) -> bool:
        if self._speech_end is None:
            self._speech_end = self._clock()
        try:
            processed = self._engine.submit_answer(self._sid, text, utterance_complete=True)
        except EngineError as exc:
            self.notices.append(str(exc))
            return False
        if processed:
            self.transcript.append(("farmer", ANSWER_PLACEHOLDER))
        return processed

    def handle_farmer_audio(self, audio: bytes) -> bool:
        self._speech_end = self._clock()           # recording stopped = utterance complete
        if not audio:
            return self.signal_silence()
        text = self._stt.transcribe(audio, self.language)
        if not text or not text.strip():
            return self.signal_silence()
        return self.handle_farmer_text(text)

    def signal_silence(self) -> bool:
        if self._speech_end is None:
            self._speech_end = self._clock()
        try:
            self._engine.submit_event(self._sid, EVENT_TIMEOUT)
        except EventUnsupported:
            self.notices.append("The engine does not support timeouts yet, so silence was ignored.")
            return False
        except EngineError as exc:
            self.notices.append(str(exc))
            return False
        self.transcript.append(("farmer", "(silence)"))
        return True

    def hang_up(self) -> bool:
        try:
            self._engine.submit_event(self._sid, EVENT_CALL_DROPPED)
        except EventUnsupported:
            self.notices.append("The engine does not support call-dropped yet, so no record was produced.")
            self.ended = True
            return False
        except EngineError as exc:
            self.notices.append(str(exc))
            return False
        self.ended = True
        return True

    # -- result ----------------------------------------------------------
    def result(self) -> Optional[dict]:
        if self._result is None and self._sid is not None:
            try:
                self._result = self._engine.get_response(self._sid)
            except EngineError:
                return None
        return self._result

    def validation_errors(self) -> Optional[list]:
        rec = self.result()
        return None if rec is None else self._agent.validate_response(rec)

    def save_result(self) -> Optional[str]:
        rec = self.result()
        return None if rec is None else self._agent.submit_response(rec)
