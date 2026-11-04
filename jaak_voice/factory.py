"""Builds the four port implementations from Settings. Swap one by changing one config value."""
from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass, field
from typing import Any

from .config import Settings

ENGINES = {"jaak": "jaak_voice.jaak_engine_adapter:JaakEngineAdapter"}
AGENTS = {"local": "jaak_voice.agent_local:LocalScenarioAdapter"}
STTS = {"transcribe": "jaak_voice.stt:TranscribeSTT", "fake": "jaak_voice.stt:FakeSTT"}
TTSS = {"polly": "jaak_voice.tts:PollyTTS", "fake": "jaak_voice.tts:FakeTTS"}


@dataclass
class Components:
    engine: Any
    agent: Any
    stt: Any
    tts: Any
    backend: str = "Fake"            # "Real AWS", "Fake" or "Mixed"
    banners: list = field(default_factory=list)


def aws_available() -> bool:
    """True when boto3 is importable and credentials can be resolved."""
    try:
        import boto3  # lazy: the core never needs it
        return boto3.Session().get_credentials() is not None
    except Exception:  # noqa: BLE001
        return False


def _load(name: str, table: dict):
    target = table.get(name, name)
    if ":" not in target:
        raise ValueError(f"unknown implementation {name!r}")
    mod, cls = target.split(":", 1)
    return getattr(importlib.import_module(mod), cls)


def _make(cls, **available):
    params = inspect.signature(cls).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return cls(**available)
    return cls(**{k: v for k, v in available.items() if k in params})


def build(settings: Settings, *, aws_ok: bool | None = None) -> Components:
    ok = aws_available() if aws_ok is None else aws_ok
    kw = dict(region=settings.region, voice=settings.voice, bucket=settings.s3_bucket,
              outputs_dir=settings.outputs_dir)
    banners: list = []
    stt_name, tts_name = settings.stt, settings.tts
    real = {"stt": False, "tts": False}

    if stt_name in ("auto", "transcribe"):
        if ok and settings.s3_bucket:
            stt_name, real["stt"] = "transcribe", True
        else:
            why = "no AWS credentials" if not ok else "JAAK_VOICE_S3_BUCKET is not set"
            banners.append(f"Speech-to-text is using the Fake implementation ({why}). Use the typed box to answer.")
            stt_name = "fake"
    elif stt_name != "fake":
        real["stt"] = True
    if tts_name in ("auto", "polly"):
        if ok:
            tts_name, real["tts"] = "polly", True
        else:
            banners.append("Text-to-speech is using the Fake implementation (no AWS credentials): JAAK's replies are silent.")
            tts_name = "fake"
    elif tts_name != "fake":
        real["tts"] = True

    backend = "Real AWS" if all(real.values()) else ("Fake" if not any(real.values()) else "Mixed")
    return Components(
        engine=_make(_load(settings.engine, ENGINES), **kw),
        agent=_make(_load(settings.agent, AGENTS), **kw),
        stt=_make(_load(stt_name, STTS), **kw),
        tts=_make(_load(tts_name, TTSS), **kw),
        backend=backend, banners=banners,
    )
