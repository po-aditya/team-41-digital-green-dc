"""Smoke tests using the Fakes only: no microphone, AWS or network."""
import subprocess
import sys
from pathlib import Path

import pytest

from jaak_voice.cli import run_scripted_call

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("language", ["en-IN", "hi-IN"])
def test_scripted_call_ends_with_valid_record(language, tmp_path):
    call, record, errors = run_scripted_call("1-mustard-aphid-spray", language, tmp_path)
    assert record is not None and errors == []
    assert record["status"] == "completed" and record["channel"] == "voice"
    assert record["language"] == language
    assert call.ended and call.last_latency_ms is not None
    assert call.save_result() and list(tmp_path.glob("*.json"))


def _py(code: str):
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                          env={"PYTHONPATH": str(ROOT), "PATH": ""})


BLOCK = "import sys; sys.modules['boto3']=None; sys.modules['streamlit']=None; sys.modules['botocore']=None; "


def test_engine_imports_without_boto3_or_streamlit():
    r = _py(BLOCK + "import mel_agent.jaak")
    assert r.returncode == 0, r.stderr


def test_orchestrator_and_ports_import_without_boto3_or_streamlit():
    r = _py(BLOCK + "import jaak_voice.orchestrator, jaak_voice.ports, jaak_voice.cli")
    assert r.returncode == 0, r.stderr


def test_only_the_engine_adapter_imports_the_engine_package():
    offenders = [p.name for p in (ROOT / "jaak_voice").glob("*.py")
                 if "mel_agent.jaak" in p.read_text(encoding="utf-8") and p.name != "jaak_engine_adapter.py"]
    assert offenders == []
