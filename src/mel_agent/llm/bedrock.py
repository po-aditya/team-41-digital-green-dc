"""Thin Amazon Bedrock adapter.

- Credentials come only from boto3's default provider chain.
- ``discover`` lists foundation models and inference profiles (free control-plane calls).
- ``BedrockInvoker.converse`` makes one Converse API call and returns the text
  plus token usage, latency and an estimated cost (when pricing is configured).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from mel_agent.config import Settings
from mel_agent.llm.pricing import PricingTable, TokenUsage


class BedrockConfigError(RuntimeError):
    pass


def _session(settings: Settings) -> boto3.Session:
    region = settings.resolved_bedrock_region
    if not region:
        raise BedrockConfigError(
            "No AWS region configured. Set MEL_BEDROCK_REGION (or AWS_REGION / AWS_DEFAULT_REGION), "
            "e.g. MEL_BEDROCK_REGION=us-west-2. No region is assumed by default."
        )
    return boto3.Session(region_name=region)


def credentials_available(settings: Settings | None = None) -> bool:
    """True if the provider chain yields credentials. Never returns or logs them."""
    try:
        session = boto3.Session()
        return session.get_credentials() is not None
    except Exception:
        return False


def make_client(settings: Settings, service: str = "bedrock-runtime", total_max_attempts: int | None = None):
    """boto3 client. ``total_max_attempts`` overrides the SDK retry budget (paid clients use 1:
    every billable attempt must be an explicit, reserved application attempt)."""
    attempts = int(total_max_attempts if total_max_attempts is not None else settings.bedrock_total_max_attempts)
    cfg = BotoConfig(
        connect_timeout=settings.bedrock_connect_timeout_s,
        read_timeout=settings.bedrock_read_timeout_s,
        retries={"total_max_attempts": attempts, "mode": "standard" if attempts == 1 else "adaptive"},
    )
    return _session(settings).client(service, config=cfg)


def sdk_total_max_attempts(client) -> int | None:
    """The SDK retry budget a client was built with, or None when it is botocore's implicit default."""
    retries = getattr(getattr(client, "meta", None), "config", None)
    retries = getattr(retries, "retries", None) or {}
    value = retries.get("total_max_attempts")
    if value is None and "max_attempts" in retries:
        value = int(retries["max_attempts"]) + 1
    return None if value is None else int(value)


def retry_attempts_in(response_or_error: Any) -> int | None:
    """Transport retries botocore reports for a call, in three explicit states.

    - a non-negative int: VERIFIED count (0 = verified zero retries, >0 = verified retries);
    - None: UNKNOWN. The envelope is not a dict, ``ResponseMetadata`` is missing or not a dict,
      ``RetryAttempts`` is missing, or it is a bool, str, float, negative number or any other
      non-int value.
    Unknown never collapses to zero: at the paid-call accounting boundary (llm/budgeted.py) an
    unknown count means the reservation stays committed as unresolved. botocore sets this field
    on every real response and ClientError payload, so a missing field is itself a red flag."""
    if not isinstance(response_or_error, dict):
        return None
    meta = response_or_error.get("ResponseMetadata")
    if not isinstance(meta, dict) or "RetryAttempts" not in meta:
        return None
    value = meta["RetryAttempts"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


@dataclass
class DiscoveryResult:
    region: str
    inference_profiles: list[dict[str, str]] = field(default_factory=list)
    foundation_models: list[dict[str, Any]] = field(default_factory=list)


def discover(settings: Settings, provider_filter: str | None = None) -> DiscoveryResult:
    """List inference profiles and text foundation models visible in the region.

    Listing does not prove invocation access; only a real call does.
    """
    client = make_client(settings, service="bedrock")
    result = DiscoveryResult(region=client.meta.region_name)

    token = None
    while True:
        kwargs: dict[str, Any] = {"maxResults": 1000}
        if token:
            kwargs["nextToken"] = token
        page = client.list_inference_profiles(**kwargs)
        for p in page.get("inferenceProfileSummaries", []):
            pid = p["inferenceProfileId"]
            if provider_filter and provider_filter not in pid:
                continue
            result.inference_profiles.append({"id": pid, "name": p.get("inferenceProfileName", ""), "status": p.get("status", "")})
        token = page.get("nextToken")
        if not token:
            break

    models = client.list_foundation_models(byOutputModality="TEXT").get("modelSummaries", [])
    for m in models:
        if provider_filter and provider_filter not in m["modelId"]:
            continue
        result.foundation_models.append(
            {
                "id": m["modelId"],
                "name": m.get("modelName", ""),
                "inference_types": m.get("inferenceTypesSupported", []),
                "lifecycle": m.get("modelLifecycle", {}).get("status", ""),
            }
        )
    result.inference_profiles.sort(key=lambda x: x["id"])
    result.foundation_models.sort(key=lambda x: x["id"])
    return result


@dataclass
class InferenceResult:
    model_id: str
    text: str
    stop_reason: str | None
    usage: TokenUsage | None  # None = the response did not establish usage (never treated as zero)
    latency_ms: float  # wall clock measured here, includes network
    server_latency_ms: int | None  # Bedrock's own metrics.latencyMs
    estimated_cost_usd: float | None  # None when usage is unknown or the model has no pricing entry
    retry_attempts: int | None = None  # verified transport retry count; None = unknown/malformed metadata (billing treated as uncertain)

    @property
    def usage_verified(self) -> bool:
        return self.usage is not None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["usage"] = asdict(self.usage) if self.usage is not None else None
        d["usage_verified"] = self.usage_verified
        return d


class BedrockInvoker:
    def __init__(self, settings: Settings, pricing: PricingTable | None = None, client=None,
                 sdk_total_max_attempts: int | None = None) -> None:
        self.settings = settings
        self.pricing = pricing
        self._client = client
        self.sdk_total_max_attempts = sdk_total_max_attempts

    @property
    def client(self):
        if self._client is None:
            self._client = make_client(self.settings, total_max_attempts=self.sdk_total_max_attempts)
        return self._client

    def converse(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model_id: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> InferenceResult:
        model = model_id or self.settings.bedrock_model_id
        inference_config: dict[str, Any] = {"maxTokens": max_tokens or self.settings.bedrock_max_tokens}
        temp = temperature if temperature is not None else self.settings.bedrock_temperature
        if temp is not None:
            inference_config["temperature"] = temp

        request: dict[str, Any] = {
            "modelId": model,
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": inference_config,
        }
        if system:
            request["system"] = [{"text": system}]

        started = time.perf_counter()
        response = self.client.converse(**request)
        latency_ms = (time.perf_counter() - started) * 1000

        blocks = response.get("output", {}).get("message", {}).get("content", []) if isinstance(response.get("output"), dict) else []
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str))
        usage = parse_usage(response.get("usage"), text)
        cost = self.pricing.estimate_cost(model, usage) if (self.pricing and usage is not None) else None

        return InferenceResult(
            model_id=model,
            text=text,
            stop_reason=response.get("stopReason"),
            usage=usage,
            latency_ms=round(latency_ms, 1),
            server_latency_ms=(response.get("metrics") or {}).get("latencyMs") if isinstance(response.get("metrics"), dict) else None,
            estimated_cost_usd=cost,
            retry_attempts=retry_attempts_in(response),
        )


def parse_usage(raw: Any, text: str) -> TokenUsage | None:
    """Return verified token usage, or None when the response does not establish it.

    Missing usage, a non-object usage block, non-integer or negative counters, and a
    reply that carries text while claiming zero output tokens are all "unknown":
    the caller must then keep its reservation committed (fail closed) rather than
    settle at $0."""
    if not isinstance(raw, dict):
        return None
    counters: dict[str, int] = {}
    for key in ("inputTokens", "outputTokens"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        counters[key] = value
    for key in ("cacheReadInputTokens", "cacheWriteInputTokens"):
        value = raw.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        counters[key] = value
    if text and counters["outputTokens"] == 0:
        return None  # text came back but was not metered: cannot be a verified zero
    return TokenUsage(
        input_tokens=counters["inputTokens"], output_tokens=counters["outputTokens"],
        cache_read_tokens=counters["cacheReadInputTokens"], cache_write_tokens=counters["cacheWriteInputTokens"],
    )
