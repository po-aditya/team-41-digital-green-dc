"""R1 + R2: pricing errors never echo file content, and bad bytes fail cleanly.

A synthetic secret-like SENTINEL is planted in invalid pricing data. It must
not appear in exception messages, stdout, stderr or logs, whether the error
comes from the library, the smoke CLI (in-process and as a real subprocess),
or the pricing-refresh CLI. No test here can reach AWS: credentials are
removed and every call path into boto3 / Bedrock is blocked.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mel_agent.llm import PricingConfigError, PricingTable, parse_pricing

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "AKIASENTINEL0SECRET0DO0NOT0ECHO0wJalrXUtnFEMI"
VALID_PRICE = {"input": 1.0, "output": 2.0}


def _doc(model_id="us.anthropic.claude-haiku-5-5", prices=None) -> dict:
    return {"models": {model_id: {"usd_per_million_tokens": prices if prices is not None else dict(VALID_PRICE)}}}


# Each case plants the sentinel somewhere different in an invalid document.
LEAK_CASES = {
    "string_input_price": _doc(prices={"input": SENTINEL, "output": 2.0}),
    "string_output_price": _doc(prices={"input": 1.0, "output": SENTINEL}),
    "string_cache_price": _doc(prices={**VALID_PRICE, "cache_read": SENTINEL}),
    "array_price": _doc(prices={"input": [SENTINEL], "output": 2.0}),
    "object_price": _doc(prices={"input": {"k": SENTINEL}, "output": 2.0}),
    "prices_not_object": {"models": {"us.x": {"usd_per_million_tokens": SENTINEL}}},
    "entry_not_object": {"models": {"us.x": SENTINEL}},
    "sentinel_as_model_id": _doc(model_id=SENTINEL, prices={"input": "bad", "output": 2.0}),
    "sentinel_model_id_missing_prices": {"models": {SENTINEL: {}}},
    "huge_number": _doc(prices={"input": 10**400, "output": 2.0}),
}


def _assert_clean(*texts: str) -> None:
    for text in texts:
        assert SENTINEL not in text
        assert SENTINEL.lower() not in text.lower()


# ---------- library level ----------


@pytest.mark.parametrize("case", sorted(LEAK_CASES))
def test_parse_errors_do_not_echo_values(case, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(PricingConfigError) as exc:
        parse_pricing(LEAK_CASES[case])
    message = str(exc.value)
    _assert_clean(message, repr(exc.value), caplog.text)
    assert "must be" in message  # still says what was expected


def test_error_names_model_field_and_rule_but_not_value():
    with pytest.raises(PricingConfigError) as exc:
        parse_pricing(_doc(prices={"input": SENTINEL, "output": 2.0}))
    msg = str(exc.value)
    assert "model entry #1" in msg
    assert "us.anthropic.claude-haiku-5-5" not in msg  # file keys are never echoed, even plausible ones
    assert "'input'" in msg and "greater than 0" in msg and "string" in msg


def test_model_key_is_replaced_by_position():
    with pytest.raises(PricingConfigError) as exc:
        parse_pricing(LEAK_CASES["sentinel_as_model_id"])
    assert "model entry #1" in str(exc.value)


@pytest.mark.parametrize("case", sorted(LEAK_CASES))
def test_load_from_file_does_not_echo_values(case, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps(LEAK_CASES[case]))
    with pytest.raises(PricingConfigError) as exc:
        PricingTable.load(path)
    _assert_clean(str(exc.value), caplog.text)


def test_json_syntax_error_does_not_echo_content(tmp_path):
    path = tmp_path / "pricing.json"
    path.write_text('{"models": {"us.x": ' + SENTINEL + "}}")  # bare token: invalid JSON
    with pytest.raises(PricingConfigError) as exc:
        PricingTable.load(path)
    assert "not valid JSON" in str(exc.value)
    _assert_clean(str(exc.value))


# ---------- R2: invalid UTF-8 ----------

INVALID_UTF8 = b'{"models": {"us.x": {"usd_per_million_tokens": {"input": "\xff\xfe' + SENTINEL.encode() + b'"}}}}'


def test_invalid_utf8_raises_pricing_config_error(tmp_path):
    path = tmp_path / "pricing.json"
    path.write_bytes(INVALID_UTF8)
    with pytest.raises(PricingConfigError) as exc:
        PricingTable.load(path)
    msg = str(exc.value)
    assert "not valid UTF-8" in msg and "byte offset" in msg
    _assert_clean(msg)
    assert "\\xff" not in msg and "�" not in msg


# ---------- smoke CLI, in-process ----------


@pytest.fixture
def smoke_isolated(load_script, monkeypatch, no_aws, clean_mel_env, tmp_path):
    """Smoke CLI with region set and every route to AWS blocked (any use fails the test)."""
    module = load_script("bedrock_smoke")

    def forbidden(*_a, **_k):
        raise AssertionError("AWS was contacted or credentials were requested")

    monkeypatch.setattr(module, "credentials_available", forbidden)
    monkeypatch.setattr(module.BedrockInvoker, "converse", forbidden)
    monkeypatch.setattr("mel_agent.llm.bedrock.boto3.Session", forbidden)
    monkeypatch.setattr("mel_agent.llm.bedrock.boto3.client", forbidden)
    monkeypatch.setenv("MEL_BEDROCK_REGION", "us-west-2")
    monkeypatch.setenv("MEL_ALLOW_PAID_INFERENCE", "true")  # authorised, so the pricing check is what fails
    monkeypatch.setenv("MEL_DATABASE_URL", f"sqlite:///{tmp_path / 'ledger.db'}")
    pricing = tmp_path / "pricing.json"
    monkeypatch.setenv("MEL_PRICING_FILE", str(pricing))
    return module, pricing


@pytest.mark.parametrize("case", sorted(LEAK_CASES))
def test_smoke_cli_does_not_echo_pricing_values(smoke_isolated, case, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    module, pricing = smoke_isolated
    pricing.write_text(json.dumps(LEAK_CASES[case]))
    assert module.main(["--yes"]) == 2
    out = capsys.readouterr()
    _assert_clean(out.out, out.err, caplog.text)
    assert out.err.startswith("ERROR: ") and out.err.count("\n") == 1


def test_smoke_cli_invalid_utf8_exit_2_without_aws(smoke_isolated, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    module, pricing = smoke_isolated
    pricing.write_bytes(INVALID_UTF8)
    assert module.main(["--yes"]) == 2  # forbidden() proves no credentials/Bedrock use
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.count("\n") == 1 and "not valid UTF-8" in out.err
    assert "Traceback" not in out.err
    _assert_clean(out.out, out.err, caplog.text)


# ---------- smoke CLI, real subprocess (stdout/stderr exactly as a user sees them) ----------


def _run_smoke_subprocess(tmp_path: Path, pricing_bytes: bytes) -> subprocess.CompletedProcess:
    pricing = tmp_path / "pricing.json"
    pricing.write_bytes(pricing_bytes)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "MEL_"))}
    env.update(
        MEL_BEDROCK_REGION="us-west-2",
        MEL_ALLOW_PAID_INFERENCE="true",
        MEL_DATABASE_URL=f"sqlite:///{tmp_path / 'ledger.db'}",
        MEL_PRICING_FILE=str(pricing),
        # No credentials anywhere, so even a regression could not make a paid call.
        AWS_SHARED_CREDENTIALS_FILE="/nonexistent",
        AWS_CONFIG_FILE="/nonexistent",
        AWS_EC2_METADATA_DISABLED="true",
    )
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "bedrock_smoke.py"), "--yes"],
        cwd=tmp_path,  # no stray .env is picked up
        env=env,
        capture_output=True,
        timeout=60,
    )


@pytest.mark.parametrize(
    "label,payload",
    [
        ("invalid_utf8", INVALID_UTF8),
        ("string_price", json.dumps(LEAK_CASES["string_input_price"]).encode()),
        ("sentinel_model_id", json.dumps(LEAK_CASES["sentinel_model_id_missing_prices"]).encode()),
    ],
)
def test_smoke_cli_subprocess_clean_failure(tmp_path, label, payload):
    proc = _run_smoke_subprocess(tmp_path, payload)
    stdout = proc.stdout.decode("utf-8", "replace")
    stderr = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 2, stderr
    assert stdout == ""
    assert stderr.startswith("ERROR: ") and stderr.count("\n") == 1, stderr
    assert "Traceback" not in stderr
    assert "credentials" not in stderr  # failed before the credential check
    _assert_clean(stdout, stderr)
    assert SENTINEL.encode() not in proc.stdout + proc.stderr


# ---------- pricing-refresh CLI ----------


@pytest.fixture
def refresh(load_script):
    return load_script("fetch_bedrock_pricing")


def test_refresh_cli_does_not_echo_invalid_fetched_values(refresh, tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    table = {
        m: {"display_name": m, "usd_per_million_tokens": dict(VALID_PRICE), "source_usage_types": []}
        for m in refresh.required_model_ids()
    }
    table["us.anthropic.claude-haiku-5-5"]["usd_per_million_tokens"]["input"] = SENTINEL
    out_file = tmp_path / "pricing.json"
    assert refresh.main(["--region", "us-west-2", "--out", str(out_file)], fetcher=lambda r: table) == 1
    out = capsys.readouterr()
    _assert_clean(out.out, out.err, caplog.text)
    assert "fetched pricing is invalid" in out.err and not out_file.exists()


def test_refresh_cli_does_not_echo_malformed_aws_response(refresh, tmp_path, capsys, caplog, monkeypatch):
    """A non-numeric price inside a Price List response must not leak via a traceback."""
    caplog.set_level(logging.DEBUG)
    product = {
        "product": {"attributes": {"usagetype": "USW2-MP:USW2_input_tokens_standard-Units"}},
        "terms": {"OnDemand": {"t": {"priceDimensions": {"d": {"unit": "1M tokens", "pricePerUnit": {"USD": SENTINEL}}}}}},
    }

    class FakePaginator:
        def paginate(self, **_):
            yield {"PriceList": [json.dumps(product)]}

    class FakeClient:
        def get_paginator(self, _name):
            return FakePaginator()

    monkeypatch.setattr(refresh.boto3, "client", lambda *a, **k: FakeClient())
    out_file = tmp_path / "pricing.json"
    assert refresh.main(["--region", "us-west-2", "--out", str(out_file)]) == 1
    out = capsys.readouterr()
    _assert_clean(out.out, out.err, caplog.text)
    assert "unexpected AWS Price List response format" in out.err and not out_file.exists()
