"""Bedrock Converse wrapper. Forces a JSON tool call so output is always structured,
and records tokens, latency and (if prices are set) cost for every call."""
import json
import os
import threading
import time
from dataclasses import dataclass, field

import boto3
from botocore.config import Config

from . import config

_local = threading.local()


def _client():
    if not hasattr(_local, "client"):
        _local.client = boto3.client(
            "bedrock-runtime", region_name=config.AWS_REGION,
            config=Config(retries={"max_attempts": 8, "mode": "adaptive"}, read_timeout=120))
    return _local.client


def _price(model):
    raw = config.WRITER_PRICE if model == config.WRITER_MODEL else config.CHECKER_PRICE
    if not raw:
        return None
    i, o = (float(x) for x in raw.split(","))
    return i, o


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    cost_usd: float | None = None
    by_model: dict = field(default_factory=dict)
    retries: int = 0  # botocore retries (throttling, timeouts) before calls succeeded

    def add(self, model, inp, out, secs):
        self.calls += 1
        self.input_tokens += inp
        self.output_tokens += out
        self.seconds += secs
        m = self.by_model.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0})
        m["calls"] += 1
        m["input_tokens"] += inp
        m["output_tokens"] += out
        m["seconds"] = round(m["seconds"] + secs, 3)
        p = _price(model)
        if p:
            self.cost_usd = (self.cost_usd or 0.0) + inp / 1e6 * p[0] + out / 1e6 * p[1]

    def merge(self, other):
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.seconds += other.seconds
        if other.cost_usd is not None:
            self.cost_usd = (self.cost_usd or 0.0) + other.cost_usd
        for model, m in other.by_model.items():
            mine = self.by_model.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0})
            for k in ("calls", "input_tokens", "output_tokens"):
                mine[k] += m[k]
            mine["seconds"] = round(mine["seconds"] + m["seconds"], 3)

    def to_dict(self):
        return {"calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "seconds": round(self.seconds, 3),
                "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 6), "by_model": self.by_model,
                "retries": self.retries}


def call_tool(model, system, user, tool_name, tool_description, schema, usage, max_tokens=1500, temperature=None):
    # temperature is left unset by default: newer Claude models on Bedrock reject it.
    """Calls the model and returns the arguments of the forced tool call as a dict."""
    if os.environ.get("MEL_ALLOW_PAID_INFERENCE") != "true":
        raise RuntimeError("Paid inference is disabled; set MEL_ALLOW_PAID_INFERENCE=true to opt in.")
    tool = {"toolSpec": {"name": tool_name, "description": tool_description, "inputSchema": {"json": schema}}}
    # Some newer models reject a forced toolChoice, so "auto" is used with a clear instruction,
    # and a JSON reply in plain text is accepted as a fallback.
    system = system + f"\n\nAlways answer by calling the {tool_name} tool exactly once."
    required = schema.get("required", [])
    problem = None
    for attempt in range(3):
        prompt = user if not problem else f"{user}\n\nYour last reply was not usable ({problem}). Call {tool_name} with every required field."
        t0 = time.time()
        resp = _client().converse(
            modelId=model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max_tokens, **({"temperature": temperature} if temperature is not None else {})},
            toolConfig={"tools": [tool], "toolChoice": {"auto": {}}},
        )
        u = resp.get("usage", {})
        usage.add(model, u.get("inputTokens", 0), u.get("outputTokens", 0), time.time() - t0)
        usage.retries += resp.get("ResponseMetadata", {}).get("RetryAttempts", 0)
        out = _extract(resp["output"]["message"]["content"])
        if out is None:
            problem = f"no {tool_name} call, stopReason={resp.get('stopReason')}"
            continue
        missing = [k for k in required if k not in out]
        if missing:
            problem = f"missing fields {missing}"
            continue
        return out
    raise ValueError(f"{model}: {problem} after 3 tries")


def _extract(content):
    for block in content:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    text = "".join(b.get("text", "") for b in content)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None
