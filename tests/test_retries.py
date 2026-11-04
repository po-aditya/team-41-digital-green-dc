"""Fix 2: the configured attempt limit is the TOTAL number of requests, initial one included."""

from __future__ import annotations

import pytest
from botocore.awsrequest import AWSResponse
from botocore.exceptions import ClientError

from mel_agent.config import Settings
from mel_agent.llm.bedrock import make_client


class _RawBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def stream(self, **_):
        yield self._data


def _count_attempts(monkeypatch, total_max_attempts: int) -> int:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.setattr("botocore.endpoint.time.sleep", lambda _s: None)  # no real backoff waits

    settings = Settings(bedrock_region="us-west-2", bedrock_total_max_attempts=total_max_attempts, _env_file=None)
    client = make_client(settings)
    calls = []

    def fake_send(request, **_):
        # Short-circuits the HTTP send; botocore's retry logic still runs on the response.
        calls.append(request.url)
        return AWSResponse(
            request.url,
            503,
            {"x-amzn-ErrorType": "ServiceUnavailableException", "Content-Type": "application/json"},
            _RawBody(b'{"message":"try again"}'),
        )

    client.meta.events.register("before-send.bedrock-runtime.Converse", fake_send)
    with pytest.raises(ClientError):
        client.converse(modelId="m", messages=[{"role": "user", "content": [{"text": "hi"}]}])
    return len(calls)


def test_botocore_config_uses_total_max_attempts():
    settings = Settings(bedrock_region="us-west-2", bedrock_total_max_attempts=3, _env_file=None)
    retries = make_client(settings).meta.config.retries
    assert retries["total_max_attempts"] == 3
    assert "max_attempts" not in retries


def test_limit_of_three_means_exactly_three_requests(monkeypatch):
    assert _count_attempts(monkeypatch, 3) == 3


def test_limit_of_one_means_no_retries(monkeypatch):
    assert _count_attempts(monkeypatch, 1) == 1


def test_env_var_name(monkeypatch):
    monkeypatch.setenv("MEL_BEDROCK_TOTAL_MAX_ATTEMPTS", "5")
    assert Settings(_env_file=None).bedrock_total_max_attempts == 5
