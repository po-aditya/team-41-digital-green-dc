"""Application settings, loaded from environment variables (prefix ``MEL_``).

AWS credentials are deliberately NOT part of these settings. boto3 resolves
them through its standard provider chain (env vars, shared config/SSO,
container or instance role), so nothing secret ever passes through here.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

def _project_root() -> Path:
    """source-code/ when running from a checkout (editable install); otherwise the
    working directory, since a regular install puts this file in site-packages."""
    checkout = Path(__file__).resolve().parents[2]
    return checkout if (checkout / "pyproject.toml").is_file() else Path.cwd()


# Project root, and the participant pack that sits next to it.
PROJECT_ROOT = _project_root()
_DEFAULT_PACK_DIR = PROJECT_ROOT.parent / "mel-survey-agent-participant-pack" / "participant-pack"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Read-only input data supplied by Digital Green. Never written to.
    participant_pack_dir: Path = _DEFAULT_PACK_DIR

    # SQLite now; the URL form keeps a later move to PostgreSQL a config change.
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'var' / 'mel.db'}"

    # --- Amazon Bedrock -------------------------------------------------
    # Falls back to AWS_REGION / AWS_DEFAULT_REGION when unset.
    bedrock_region: str | None = None
    # A model id or an inference-profile id (e.g. "us.anthropic.claude-haiku-5-5").
    bedrock_model_id: str = "us.anthropic.claude-haiku-5-5"
    bedrock_max_tokens: int = Field(default=1024, ge=1, le=64000)
    # None = omit the parameter and use the model's default.
    bedrock_temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    bedrock_connect_timeout_s: float = Field(default=10, gt=0)
    bedrock_read_timeout_s: float = Field(default=120, gt=0)
    # Total requests per call, INCLUDING the first one (3 = 1 try + 2 retries).
    # Passed to botocore as total_max_attempts; botocore's max_attempts would mean retries only.
    bedrock_total_max_attempts: int = Field(default=3, ge=1, le=10)

    # --- Spending controls ---------------------------------------------
    budget_max_usd: float = Field(default=250.0, gt=0)
    budget_stop_usd: float = Field(default=225.0, gt=0)
    pricing_file: Path = PROJECT_ROOT / "config" / "bedrock_pricing.json"

    @model_validator(mode="after")
    def _check_budget(self) -> "Settings":
        if self.budget_stop_usd > self.budget_max_usd:
            raise ValueError(
                f"MEL_BUDGET_STOP_USD ({self.budget_stop_usd}) must not exceed "
                f"MEL_BUDGET_MAX_USD ({self.budget_max_usd})"
            )
        return self

    @property
    def schemas_dir(self) -> Path:
        return self.participant_pack_dir / "json" / "schemas"

    @property
    def resolved_bedrock_region(self) -> str | None:
        # Empty values count as unset (Compose may forward a variable as "").
        return self.bedrock_region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
