"""Fix 1: the pricing refresh never replaces a valid file with an empty or partial one."""

from __future__ import annotations

import json
import shutil

import pytest
from botocore.exceptions import ClientError

from mel_agent.llm import PricingTable


@pytest.fixture
def refresh(load_script):
    return load_script("fetch_bedrock_pricing")


@pytest.fixture
def pricing_copy(tmp_path, settings):
    """A copy of the real pricing file; the original in config/ is never touched."""
    path = tmp_path / "bedrock_pricing.json"
    shutil.copy(settings.pricing_file, path)
    return path


def _full_table(refresh) -> dict:
    """A complete, valid fetch result for every required model (synthetic prices; tmp files only)."""
    return {
        model_id: {
            "display_name": model_id,
            "usd_per_million_tokens": {"input": 1.0, "output": 2.0, "cache_read": 0.1, "cache_write": 1.25},
            "source_usage_types": ["test"],
        }
        for model_id in refresh.required_model_ids()
    }


def _run(refresh, out, table=None, exc=None, extra=()):
    def fetcher(region):
        if exc:
            raise exc
        return table

    return refresh.main(["--region", "us-west-2", "--out", str(out), *extra], fetcher=fetcher)


def _no_temp_files(path):
    return [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_empty_result_fails_and_keeps_file(refresh, pricing_copy, capsys):
    before = pricing_copy.read_bytes()
    assert _run(refresh, pricing_copy, table={}) == 1
    assert pricing_copy.read_bytes() == before
    assert "no pricing" in capsys.readouterr().err
    assert _no_temp_files(pricing_copy)


def test_missing_required_model_fails_and_keeps_file(refresh, pricing_copy, capsys):
    before = pricing_copy.read_bytes()
    table = _full_table(refresh)
    del table["us.anthropic.claude-haiku-5-5"]  # the default model
    assert _run(refresh, pricing_copy, table=table) == 1
    assert pricing_copy.read_bytes() == before
    assert "us.anthropic.claude-haiku-5-5" in capsys.readouterr().err


def test_extra_required_model_is_enforced(refresh, pricing_copy):
    before = pricing_copy.read_bytes()
    assert _run(refresh, pricing_copy, table=_full_table(refresh), extra=["--require", "us.some.other-model"]) == 1
    assert pricing_copy.read_bytes() == before


@pytest.mark.parametrize("bad", [{"input": 1.0}, {"input": 0, "output": 1.0}, {"input": "1", "output": 1.0}])
def test_incomplete_or_invalid_prices_fail_and_keep_file(refresh, pricing_copy, bad):
    before = pricing_copy.read_bytes()
    table = _full_table(refresh)
    table["us.anthropic.claude-sonnet-5-5"]["usd_per_million_tokens"] = bad
    assert _run(refresh, pricing_copy, table=table) == 1
    assert pricing_copy.read_bytes() == before


def test_aws_error_fails_and_keeps_file(refresh, pricing_copy):
    before = pricing_copy.read_bytes()
    err = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "GetProducts")
    assert _run(refresh, pricing_copy, exc=err) == 1
    assert pricing_copy.read_bytes() == before


def test_failed_write_keeps_file_and_cleans_temp(refresh, pricing_copy, monkeypatch):
    before = pricing_copy.read_bytes()

    def boom(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(refresh.os, "replace", boom)
    assert _run(refresh, pricing_copy, table=_full_table(refresh)) == 1
    assert pricing_copy.read_bytes() == before
    assert _no_temp_files(pricing_copy)


def test_region_is_required(refresh, pricing_copy):
    with pytest.raises(SystemExit) as exc:
        refresh.main(["--out", str(pricing_copy)], fetcher=lambda r: {})
    assert exc.value.code == 2


def test_valid_result_is_written_atomically_and_loadable(refresh, tmp_path):
    out = tmp_path / "new.json"
    assert _run(refresh, out, table=_full_table(refresh)) == 0
    table = PricingTable.load(out)
    assert set(table.prices) == set(refresh.required_model_ids())
    assert json.loads(out.read_text())["_meta"]["region"] == "us-west-2"
    assert _no_temp_files(out)


def test_committed_pricing_file_satisfies_refresh_requirements(refresh, settings):
    table = PricingTable.load(settings.pricing_file)
    assert set(refresh.required_model_ids()) <= set(table.prices)
