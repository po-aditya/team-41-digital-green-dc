"""TextToSpeech implementations. Both return WAV bytes (16 kHz, mono, 16-bit)."""
from __future__ import annotations

import io
import wave

RATE = 16000


def _wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


class FakeTTS:
    """Silent WAV, 0.3 seconds."""

    def synthesize(self, text: str, language: str) -> bytes:
        return _wav(b"\x00\x00" * int(RATE * 0.3))


class PollyTTS:
    """Amazon Polly neural voice (Kajal speaks both hi-IN and en-IN)."""

    def __init__(self, region: str, voice: str = "Kajal") -> None:
        import boto3
        self._polly = boto3.client("polly", region_name=region)
        self._voice = voice

    def synthesize(self, text: str, language: str) -> bytes:
        if language not in ("hi-IN", "en-IN"):
            raise ValueError("unsupported language")
        resp = self._polly.synthesize_speech(Text=text, VoiceId=self._voice, Engine="neural",
                                             LanguageCode=language, OutputFormat="pcm", SampleRate=str(RATE))
        return _wav(resp["AudioStream"].read())


PollySTTS = PollyTTS   # alias for the spelling used in the brief
