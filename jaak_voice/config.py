"""Settings from environment variables. Each port is chosen by one value.

JAAK_VOICE_ENGINE  jaak | pkg.module:Class          (default jaak)
JAAK_VOICE_AGENT   local | pkg.module:Class         (default local)
JAAK_VOICE_STT     auto | transcribe | fake | pkg.module:Class
JAAK_VOICE_TTS     auto | polly | fake | pkg.module:Class
AWS_REGION, JAAK_VOICE_NAME (default Kajal), JAAK_VOICE_S3_BUCKET (needed by Transcribe),
JAAK_VOICE_OUTPUTS (default ./outputs)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    engine: str = "jaak"
    agent: str = "local"
    stt: str = "auto"
    tts: str = "auto"
    region: str = "us-west-2"
    voice: str = "Kajal"
    s3_bucket: Optional[str] = None
    outputs_dir: Path = ROOT / "outputs"

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        e = os.environ if env is None else env
        return cls(
            engine=e.get("JAAK_VOICE_ENGINE", "jaak"),
            agent=e.get("JAAK_VOICE_AGENT", "local"),
            stt=e.get("JAAK_VOICE_STT", "auto"),
            tts=e.get("JAAK_VOICE_TTS", "auto"),
            region=e.get("AWS_REGION") or e.get("AWS_DEFAULT_REGION") or "us-west-2",
            voice=e.get("JAAK_VOICE_NAME", "Kajal"),
            s3_bucket=e.get("JAAK_VOICE_S3_BUCKET") or None,
            outputs_dir=Path(e.get("JAAK_VOICE_OUTPUTS", str(ROOT / "outputs"))),
        )
