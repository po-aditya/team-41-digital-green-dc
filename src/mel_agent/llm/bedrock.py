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


def make_client(settings: Settings, service: str = "bedrock-runtime"):
    cfg = BotoConfig(
        connect_timeout=settings.bedrock_connect_timeout_s,
        read_timeout=settings.bedrock_read_timeout_s,
        retries={"total_max_attempts": settings.bedrock_total_max_attempts, "mode": "adaptive"},
    )
    return _session(settings).client(service, config=cfg)


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
    usage: TokenUsage
    latency_ms: float  # wall clock measured here, includes network
    server_latency_ms: int | None  # Bedrock's own metrics.latencyMs
    estimated_cost_usd: float | None  # None when the model has no pricing entry

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["usage"] = asdict(self.usage)
        return d


class BedrockInvoker:
    def __init__(self, settings: Settings, pricing: PricingTable | None = None, client=None) -> None:
        self.settings = settings
        self.pricing = pricing
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = make_client(self.settings)
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

        raw_usage = response.get("usage", {})
        usage = TokenUsage(
            input_tokens=raw_usage.get("inputTokens", 0),
            output_tokens=raw_usage.get("outputTokens", 0),
            cache_read_tokens=raw_usage.get("cacheReadInputTokens", 0),
            cache_write_tokens=raw_usage.get("cacheWriteInputTokens", 0),
        )
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        text = "".join(b.get("text", "") for b in blocks)
        cost = self.pricing.estimate_cost(model, usage) if self.pricing else None

        return InferenceResult(
            model_id=model,
            text=text,
            stop_reason=response.get("stopReason"),
            usage=usage,
            latency_ms=round(latency_ms, 1),
            server_latency_ms=response.get("metrics", {}).get("latencyMs"),
            estimated_cost_usd=cost,
        )
