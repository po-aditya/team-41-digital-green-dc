"""Model pricing and spend-limit configuration.

Prices live in ``config/bedrock_pricing.json``, generated from the AWS Price
List API by ``scripts/fetch_bedrock_pricing.py``. Nothing is hard-coded here:
a model without a pricing entry gets ``None`` as its cost, never a guess.

The full spending controller (persistent ledger, hard stop) is a later phase.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens


@dataclass(frozen=True)
class ModelPrice:
    """USD per one million tokens."""

    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None

    def cost(self, usage: TokenUsage) -> float:
        total = usage.input_tokens * self.input + usage.output_tokens * self.output
        if usage.cache_read_tokens:
            if self.cache_read is None:
                raise ValueError("cache-read tokens used but no cache_read price configured")
            total += usage.cache_read_tokens * self.cache_read
        if usage.cache_write_tokens:
            if self.cache_write is None:
                raise ValueError("cache-write tokens used but no cache_write price configured")
            total += usage.cache_write_tokens * self.cache_write
        return total / _PER_MILLION


class PricingConfigError(ValueError):
    """The pricing file is missing, unreadable or malformed.

    Messages never contain anything read from the file (neither model keys
    nor values): they name the entry position, field, expected type and
    range only, so a misplaced secret cannot leak.
    """


def _model_label(position: int) -> str:
    # Model keys are untrusted file content and are never shown, however
    # harmless they look (a credential can resemble a model id).
    return f"model entry #{position}"


def _price(value: object, field: str, label: str, required: bool) -> float | None:
    if value is None and not required:
        return None
    rule = f"{label}: '{field}' must be a finite number greater than 0 (USD per 1M tokens)"
    if value is None:
        raise PricingConfigError(f"{rule}; it is missing")
    # bool is an int subclass; reject it explicitly. Report the JSON type, never the value.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PricingConfigError(f"{rule}; found a {_json_type(value)}")
    try:
        number = float(value)
    except OverflowError:
        raise PricingConfigError(f"{rule}; found a number out of range") from None
    if not math.isfinite(number) or number <= 0:
        raise PricingConfigError(f"{rule}; found a number out of range")
    return number


def _json_type(value: object) -> str:
    return {bool: "boolean", str: "string", list: "array", dict: "object"}.get(type(value), "non-numeric value")


def parse_pricing(data: object) -> tuple[dict[str, "ModelPrice"], dict]:
    """Validate a pricing document and return (prices, meta). Raises PricingConfigError."""
    if not isinstance(data, dict):
        raise PricingConfigError("pricing document must be a JSON object")
    models = data.get("models")
    if not isinstance(models, dict) or not models:
        raise PricingConfigError("pricing document has no 'models' entries")
    prices: dict[str, ModelPrice] = {}
    for position, (model_id, entry) in enumerate(models.items(), start=1):
        label = _model_label(position)
        p = entry.get("usd_per_million_tokens") if isinstance(entry, dict) else None
        if not isinstance(p, dict):
            raise PricingConfigError(f"{label}: 'usd_per_million_tokens' must be an object")
        prices[model_id] = ModelPrice(
            input=_price(p.get("input"), "input", label, True),
            output=_price(p.get("output"), "output", label, True),
            cache_read=_price(p.get("cache_read"), "cache_read", label, False),
            cache_write=_price(p.get("cache_write"), "cache_write", label, False),
        )
    meta = data.get("_meta") or {}
    return prices, meta


class PricingTable:
    def __init__(self, prices: dict[str, ModelPrice], meta: dict | None = None) -> None:
        self.prices = prices
        self.meta = meta or {}

    @classmethod
    def load(cls, path: Path) -> "PricingTable":
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise PricingConfigError(f"pricing file not found: {path} (set MEL_PRICING_FILE)") from None
        except UnicodeDecodeError as exc:
            # Position only; the undecodable bytes are not shown.
            raise PricingConfigError(f"pricing file {path} is not valid UTF-8 (byte offset {exc.start})") from None
        except OSError as exc:
            raise PricingConfigError(f"cannot read pricing file {path}: {exc.strerror}") from None
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            # exc.msg is a fixed description such as "Expecting value"; exc.doc (the content) is not used.
            raise PricingConfigError(
                f"pricing file {path} is not valid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg})"
            ) from None
        except RecursionError:
            raise PricingConfigError(f"pricing file {path} is nested too deeply to be a pricing table") from None
        prices, meta = parse_pricing(data)
        return cls(prices, meta)

    def price_for(self, model_id: str) -> ModelPrice | None:
        return self.prices.get(model_id)

    def estimate_cost(self, model_id: str, usage: TokenUsage) -> float | None:
        price = self.price_for(model_id)
        return None if price is None else price.cost(usage)


class BudgetState(StrEnum):
    OK = "ok"
    STOP = "stop"  # reached the operational stop threshold: make no new calls
    EXCEEDED = "exceeded"  # at or over the hard maximum


def budget_state(spent_usd: float, stop_usd: float, max_usd: float) -> BudgetState:
    if spent_usd >= max_usd:
        return BudgetState.EXCEEDED
    if spent_usd >= stop_usd:
        return BudgetState.STOP
    return BudgetState.OK
