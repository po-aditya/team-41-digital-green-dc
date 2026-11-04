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

from pydantic import Field, SecretStr, model_validator
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
    # PAID inference only: the SDK never retries (1 attempt per request); the application retries
    # transient, provably unbilled failures up to this many attempts, each with its own reservation.
    bedrock_paid_app_attempts: int = Field(default=2, ge=1, le=5)
    # After a timeout the request may have been billed; retrying spends again. Off unless opted in.
    bedrock_paid_retry_after_timeout: bool = False
    # While this many reservations are unresolved (billing unknown), no new paid attempt is reserved
    # until an operator reconciles them (`python -m mel_agent budget reconcile`).
    budget_max_unresolved: int = Field(default=3, ge=1, le=100)

    # --- Spending controls (hackathon CONFIGURATION, not product rules) --
    # Finite, positive, bounded: the ledger refuses to start on anything else.
    budget_max_usd: float = Field(default=250.0, gt=0, le=1_000_000, allow_inf_nan=False)
    budget_stop_usd: float = Field(default=225.0, gt=0, le=1_000_000, allow_inf_nan=False)
    pricing_file: Path = PROJECT_ROOT / "config" / "bedrock_pricing.json"
    # Paid inference is OFF unless this is explicitly true. Tests never set it.
    allow_paid_inference: bool = False
    # Conservative token estimate for reservations: characters per token (lower = more conservative).
    budget_chars_per_token: float = Field(default=3.0, gt=0, le=100, allow_inf_nan=False)
    # Multiplier applied to every pre-call estimate before it is reserved.
    budget_safety_factor: float = Field(default=1.25, ge=1.0, le=5.0, allow_inf_nan=False)

    # --- Operator access ------------------------------------------------
    # Shared secret for workflow and record endpoints (header X-Operator-Token). Unset = those routes
    # answer 503. Minimum 16 characters. Never logged or echoed. See README "Operator access".
    operator_token: SecretStr | None = None

    # --- Survey generation ---------------------------------------------
    # "template" is deterministic and free; "bedrock" needs allow_paid_inference and budget headroom.
    generation_provider: Literal["template", "bedrock"] = "template"
    generation_max_attempts: int = Field(default=2, ge=1, le=5)
    # When the primary provider fails every attempt, fall back to the template provider.
    generation_fallback_to_template: bool = True
    # Surveys below this relevance proxy are not scheduled.
    min_relevance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    # Model-written question wording. OFF: any free-form question is rejected. ON: such surveys are
    # stored as pending_approval and are never scheduled or sent without a human decision.
    generation_allow_freeform: bool = False
    # Real-time lease on a generation claim (seconds). A crashed worker's claim can be taken over
    # only after this; simulated season time never expires a claim.
    generation_lease_seconds: int = Field(default=300, ge=5, le=86400)

    # --- Simulation ----------------------------------------------------
    simulation_seed: int = 20261104
    broadcaster_max_attempts_per_channel: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def _check_budget(self) -> "Settings":
        if self.budget_stop_usd > self.budget_max_usd:
            raise ValueError("MEL_BUDGET_STOP_USD must not exceed MEL_BUDGET_MAX_USD")
        if self.operator_token is not None and len(self.operator_token.get_secret_value()) < 16:
            raise ValueError("MEL_OPERATOR_TOKEN must be at least 16 characters")
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
