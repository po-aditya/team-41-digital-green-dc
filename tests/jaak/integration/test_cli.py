"""CLI smoke tests: subprocess runs of ``python -m mel_agent.jaak.cli run``.

Validates: Requirements 15.7, 20.1, 20.6
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mel_agent import config, data
from mel_agent.jaak.models import ResponseRecord

ROOT = Path(__file__).resolve().parents[3]
SCENARIO = Path(config.PACK) / "json" / "scenarios" / "1-mustard-aphid-spray"
CLOCK = "2026-12-07T10:00:00+05:30"
GREETING_REPLY = {"en-IN": "okay go ahead", "hi-IN": "ठीक है"}
# Option indexes picked from the shipped survey: yes / easy / fewer.
PICKS = (0, 0, 1)


def _survey_path(lang: str) -> Path:
    return SCENARIO / f"survey.{lang}.json"


def _survey(lang: str) -> dict:
    return json.loads(_survey_path(lang).read_text(encoding="utf-8"))


def _answers(lang: str) -> list[str]:
    items = _survey(lang)["items"]
    labels = [it["options"][i]["label"] for it, i in zip(items, PICKS)]
    return [GREETING_REPLY[lang], *labels]


def _write_answers(tmp_path: Path, name: str, lines: list[str]) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _run(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "mel_agent.jaak.cli", "run", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
    )


def _scripted(lang: str, answers: Path, *extra: str, survey: Path | None = None,
              farmer_id: str | None = None) -> subprocess.CompletedProcess:
    sp = survey or _survey_path(lang)
    fid = farmer_id or _survey(lang)["farmer_id"]
    return _run("--survey", str(sp), "--farmer-id", fid,
                "--answers", str(answers), "--clock", CLOCK, *extra)


def _pack_digest() -> str:
    h = hashlib.sha256()
    for p in sorted(Path(config.PACK).rglob("*")):
        h.update(str(p).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


@pytest.mark.parametrize("lang", ["en-IN", "hi-IN"])
def test_scripted_run_produces_valid_completed_record(tmp_path, lang):
    proc = _scripted(lang, _write_answers(tmp_path, "a.txt", _answers(lang)))
    assert proc.returncode == 0, proc.stderr
    record = json.loads(proc.stdout)
    assert list(data.validator("response").iter_errors(record)) == []
    ResponseRecord.model_validate(record)
    assert record["channel"] == "voice"
    assert record["language"] == lang
    assert record["status"] == "completed"


@pytest.mark.parametrize("lang", ["en-IN", "hi-IN"])
def test_repeated_runs_are_byte_identical(tmp_path, lang):
    answers = _write_answers(tmp_path, "a.txt", _answers(lang))
    first, second = _scripted(lang, answers), _scripted(lang, answers)
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert first.stdout.encode("utf-8") == second.stdout.encode("utf-8")


def test_out_inside_pack_is_refused_and_writes_nothing(tmp_path):
    answers = _write_answers(tmp_path, "a.txt", _answers("en-IN"))
    target = Path(config.PACK) / "cli_smoke_should_not_exist.json"
    before = _pack_digest()
    proc = _scripted("en-IN", answers, "--out", str(target))
    assert proc.returncode != 0
    assert proc.stdout == ""
    assert not target.exists()
    assert _pack_digest() == before


def test_out_file_matches_stdout_run(tmp_path):
    answers = _write_answers(tmp_path, "a.txt", _answers("en-IN"))
    out = tmp_path / "record.json"
    via_out = _scripted("en-IN", answers, "--out", str(out))
    via_stdout = _scripted("en-IN", answers)
    assert via_out.returncode == 0 and via_stdout.returncode == 0
    assert via_out.stdout == ""
    assert json.loads(out.read_text(encoding="utf-8")) == json.loads(via_stdout.stdout)


def test_farmer_id_mismatch_exits_2_with_one_line_error(tmp_path):
    answers = _write_answers(tmp_path, "a.txt", _answers("en-IN"))
    other = "F-000124"
    assert other != _survey("en-IN")["farmer_id"]
    proc = _scripted("en-IN", answers, farmer_id=other)
    assert proc.returncode == 2, proc.stderr
    assert proc.stdout == ""
    err = proc.stderr.strip()
    assert err.startswith("error:") and "\n" not in err


def test_answers_running_out_exits_3(tmp_path):
    answers = _write_answers(tmp_path, "a.txt", _answers("en-IN")[:2])
    proc = _scripted("en-IN", answers)
    assert proc.returncode == 3, proc.stderr
    assert proc.stdout == ""


def test_turns_go_to_stderr_not_stdout(tmp_path):
    answers = _write_answers(tmp_path, "a.txt", _answers("en-IN"))
    proc = _scripted("en-IN", answers)
    assert proc.returncode == 0
    assert "JAAK:" in proc.stderr
    assert "JAAK:" not in proc.stdout
    json.loads(proc.stdout)  # stdout is only the record


def test_missing_survey_path_exits_1(tmp_path):
    answers = _write_answers(tmp_path, "a.txt", _answers("en-IN"))
    proc = _scripted("en-IN", answers, survey=tmp_path / "nope.json")
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.startswith("error:")


def test_drop_directive_is_flexible_until_task_11_1(tmp_path):
    # Until task 11.1 the engine raises NotImplementedError for caller events and
    # the CLI prints "not supported yet" to stderr, then runs out of input (exit 3).
    # Once supported, !drop ends the session with a failure record (exit 0, status
    # failed). Either behaviour is accepted; anything else is a regression.
    answers = _write_answers(tmp_path, "a.txt", [GREETING_REPLY["en-IN"], "!drop"])
    proc = _scripted("en-IN", answers)
    if "not supported yet" in proc.stderr:
        assert proc.returncode == 3
        assert proc.stdout == ""
    else:
        assert proc.returncode == 0, proc.stderr
        record = json.loads(proc.stdout)
        assert list(data.validator("response").iter_errors(record)) == []
        assert record["status"] != "completed"
