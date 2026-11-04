"""R1 follow-up: untrusted pricing-file model KEYS are never echoed, whatever they look like.

Every sentinel below is used as a model key in an invalid pricing table and run
through all three paths: PricingTable.load(), the Bedrock smoke CLI (in-process
and as a subprocess), and the pricing-refresh CLI. Nothing here can reach AWS:
credential lookup, boto3 and Bedrock inference are blocked and fail the test if used.
All sentinels are synthetic.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mel_agent.llm import PricingConfigError, PricingTable

ROOT = Path(__file__).resolve().parents[1]

SENTINELS = {
    # 40-char lowercase hex (shape of a GitHub classic token / SHA-1 / AWS secret fragment).
    "hex40": hashlib.sha1(b"synthetic-sentinel-40").hexdigest(),
    # 64-char lowercase hex (shape of an API key / SHA-256).
    "hex64": hashlib.sha256(b"synthetic-sentinel-64").hexdigest(),
    # Credential-like string that also looks like a legitimate Bedrock profile id.
    "credential_like_model_id": "us.anthropic.sk-live-9f8e7d6c5b4a3f2e1d0c-v1:0",
    # Ordinary-looking lowercase model id: still untrusted file content, still not echoed.
    "normal_model_id": "us.anthropic.claude-internal-test-5-9",
    # The previous uppercase sentinel.
    "uppercase": "AKIASENTINEL0SECRET0DO0NOT0ECHO0wJalrXUtnFEMI",
}
assert len(SENTINELS["hex40"]) == 40 and len(SENTINELS["hex64"]) == 64

# Ways an entry keyed by the sentinel can be invalid -> (document builder, expected field in message).
SHAPES = {
    "string_price": (lambda k: {k: {"usd_per_million_tokens": {"input": "bad", "output": 1.0}}}, "'input'"),
    "missing_output": (lambda k: {k: {"usd_per_million_tokens": {"input": 1.0}}}, "'output'"),
    "negative_cache": (lambda k: {k: {"usd_per_million_tokens": {"input": 1.0, "output": 1.0, "cache_read": -1}}}, "'cache_read'"),
    "no_price_object": (lambda k: {k: {}}, "'usd_per_million_tokens'"),
    "entry_not_object": (lambda k: {k: "x"}, "'usd_per_million_tokens'"),
}
CASES = [(s, shape) for s in SENTINELS for shape in SHAPES]
IDS = [f"{s}-{shape}" for s, shape in CASES]

VALID_ENTRY = {"usd_per_million_tokens": {"input": 1.0, "output": 2.0}}


def _doc(sentinel_name: str, shape: str, valid_first: bool = True) -> dict:
    """Invalid table whose bad entry is keyed by the sentinel, placed second after a valid entry."""
    build, _ = SHAPES[shape]
    models = {"us.anthropic.claude-haiku-5-5": dict(VALID_ENTRY)} if valid_first else {}
    models.update(build(SENTINELS[sentinel_name]))
    return {"models": models}


def _assert_absent(sentinel: str, *texts: str) -> None:
    for text in texts:
        assert sentinel not in text
        assert sentinel.lower() not in text.lower()


@pytest.fixture
def no_aws_access(monkeypatch, no_aws):
    """Any credential lookup, boto3 client/session or Bedrock call fails the test."""

    def forbidden(*_a, **_k):
        raise AssertionError("AWS credentials were requested or AWS was contacted")

    import boto3

    import mel_agent.llm.bedrock as bedrock

    monkeypatch.setattr(boto3, "client", forbidden)
    monkeypatch.setattr(boto3, "Session", forbidden)
    monkeypatch.setattr(bedrock, "credentials_available", forbidden)
    monkeypatch.setattr(bedrock.BedrockInvoker, "converse", forbidden)
    return forbidden


# ---------- 1. PricingTable.load() ----------


@pytest.mark.parametrize("sentinel_name,shape", CASES, ids=IDS)
def test_load_never_echoes_model_key(tmp_path, caplog, sentinel_name, shape):
    caplog.set_level(logging.DEBUG)
    sentinel = SENTINELS[sentinel_name]
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps(_doc(sentinel_name, shape)))
    with pytest.raises(PricingConfigError) as exc:
        PricingTable.load(path)
    msg = str(exc.value)
    _assert_absent(sentinel, msg, repr(exc.value), caplog.text)
    # Useful context is kept: position, field, and the rule.
    assert "model entry #2" in msg
    assert SHAPES[shape][1] in msg
    assert "must be" in msg


def test_valid_pricing_format_still_loads(settings):
    table = PricingTable.load(settings.pricing_file)
    assert "us.anthropic.claude-haiku-5-5" in table.prices  # keys are still used, just never printed
    assert table.price_for("us.anthropic.claude-haiku-5-5").input > 0


# ---------- 2. Bedrock smoke CLI ----------


@pytest.fixture
def smoke(load_script, monkeypatch, clean_mel_env, no_aws_access, tmp_path):
    module = load_script("bedrock_smoke")
    monkeypatch.setattr(module, "credentials_available", no_aws_access)
    monkeypatch.setattr(module.BedrockInvoker, "converse", no_aws_access)
    monkeypatch.setenv("MEL_BEDROCK_REGION", "us-west-2")
    monkeypatch.setenv("MEL_ALLOW_PAID_INFERENCE", "true")
    monkeypatch.setenv("MEL_DATABASE_URL", f"sqlite:///{tmp_path / 'ledger.db'}")
    pricing = tmp_path / "pricing.json"
    monkeypatch.setenv("MEL_PRICING_FILE", str(pricing))
    return module, pricing


@pytest.mark.parametrize("sentinel_name,shape", CASES, ids=IDS)
def test_smoke_cli_never_echoes_model_key(smoke, capsys, caplog, sentinel_name, shape):
    caplog.set_level(logging.DEBUG)
    module, pricing = smoke
    pricing.write_text(json.dumps(_doc(sentinel_name, shape)))
    assert module.main(["--yes"]) == 2
    out = capsys.readouterr()
    _assert_absent(SENTINELS[sentinel_name], out.out, out.err, caplog.text)
    assert out.out == ""
    assert out.err.startswith("ERROR: ") and out.err.count("\n") == 1
    assert "model entry #2" in out.err


@pytest.mark.parametrize("sentinel_name", sorted(SENTINELS))
def test_smoke_cli_subprocess_never_echoes_model_key(tmp_path, sentinel_name):
    sentinel = SENTINELS[sentinel_name]
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps(_doc(sentinel_name, "string_price")))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "MEL_"))}
    env.update(
        MEL_BEDROCK_REGION="us-west-2",
        MEL_ALLOW_PAID_INFERENCE="true",
        MEL_DATABASE_URL=f"sqlite:///{tmp_path / 'ledger.db'}",
        MEL_PRICING_FILE=str(pricing),
        # No credentials exist for the child process, so even a regression could not spend money.
        AWS_SHARED_CREDENTIALS_FILE="/nonexistent",
        AWS_CONFIG_FILE="/nonexistent",
        AWS_EC2_METADATA_DISABLED="true",
    )
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "bedrock_smoke.py"), "--yes"],
        cwd=tmp_path, env=env, capture_output=True, timeout=60,
    )
    stdout, stderr = proc.stdout.decode(), proc.stderr.decode()
    assert proc.returncode == 2, stderr
    assert sentinel.encode() not in proc.stdout + proc.stderr
    _assert_absent(sentinel, stdout, stderr)
    assert "Traceback" not in stderr and "credentials" not in stderr
    assert stderr.count("\n") == 1 and "model entry #2" in stderr


# ---------- 3. Pricing-refresh CLI ----------


@pytest.fixture
def refresh(load_script, no_aws_access, monkeypatch):
    module = load_script("fetch_bedrock_pricing")
    monkeypatch.setattr(module.boto3, "client", no_aws_access)
    return module


@pytest.mark.parametrize("sentinel_name,shape", CASES, ids=IDS)
def test_refresh_cli_never_echoes_model_key_and_keeps_file(
    refresh, settings, tmp_path, capsys, caplog, sentinel_name, shape
):
    caplog.set_level(logging.DEBUG)
    sentinel = SENTINELS[sentinel_name]
    out_file = tmp_path / "bedrock_pricing.json"
    shutil.copy(settings.pricing_file, out_file)
    before = out_file.read_bytes()

    # Complete, valid table for every required model, plus one invalid entry keyed by the sentinel.
    table = {
        m: {"display_name": m, "usd_per_million_tokens": {"input": 1.0, "output": 2.0}, "source_usage_types": []}
        for m in refresh.required_model_ids()
    }
    table.update(SHAPES[shape][0](sentinel))

    code = refresh.main(["--region", "us-west-2", "--out", str(out_file)], fetcher=lambda _r: table)
    out = capsys.readouterr()
    assert code == 1
    assert out_file.read_bytes() == before  # existing pricing preserved
    assert [p.name for p in tmp_path.iterdir()] == ["bedrock_pricing.json"]  # no temp files left
    _assert_absent(sentinel, out.out, out.err, caplog.text)
    assert "fetched pricing is invalid" in out.err and "model entry #" in out.err
