"""Fix 3 and Fix 6: Docker build-context hygiene and lockfile consistency (offline).

Docker is not installed on the dev machine, so .dockerignore is checked with a
small simulation of Docker's rules (last matching pattern wins; a pattern that
matches a directory covers everything under it). It is an approximation, not
a substitute for a real `docker build`.
"""

from __future__ import annotations

import re
import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _rules():
    rules = []
    for line in (ROOT / ".dockerignore").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        neg = line.startswith("!")
        rules.append((neg, line.lstrip("!").rstrip("/")))
    return rules


def _match(pattern: str, path: str) -> bool:
    parts = path.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    if pattern.startswith("**/"):
        tail = pattern[3:]
        return any(fnmatchcase(p.split("/")[-1], tail) or fnmatchcase(p, tail) for p in prefixes)
    return any(fnmatchcase(p, pattern) for p in prefixes)


def _ignored(path: str) -> bool:
    ignored = False
    for neg, pattern in _rules():
        if _match(pattern, path):
            ignored = not neg
    return ignored


@pytest.mark.parametrize(
    "path",
    [
        ".env", ".env.local", ".env.production", ".env.example", "config/.env", "src/mel_agent/.env.dev",
        ".venv/bin/python", "venv/lib/x.py", ".aws/credentials", "config/aws_credentials.json",
        "certs/server.pem", "src/mel_agent/__pycache__/main.cpython-312.pyc", ".pytest_cache/v/x",
        "tests/test_app.py", "var/mel.db", "requirements/dev.lock", "requirements/tested-py314.txt",
        ".git/config", "scripts/bedrock_smoke.py", "src/mel_survey_agent.egg-info/PKG-INFO",
    ],
)
def test_sensitive_and_local_files_excluded_from_build_context(path):
    assert _ignored(path), path


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml", "README.md", "requirements/runtime.lock", "requirements/build.lock",
        "src/mel_agent/main.py", "src/mel_agent/contracts/schemas.py", "config/bedrock_pricing.json",
    ],
)
def test_files_the_dockerfile_copies_are_included(path):
    assert not _ignored(path), path


def test_every_dockerfile_copy_source_exists_and_is_in_context():
    sources = []
    for line in (ROOT / "Dockerfile").read_text().splitlines():
        if line.startswith("COPY "):
            sources += line.split()[1:-1]
    assert sources
    for src in sources:
        assert (ROOT / src).exists(), src
        assert not _ignored(src), src


def test_base_image_pinned_by_digest():
    from_line = next(l for l in (ROOT / "Dockerfile").read_text().splitlines() if l.startswith("FROM "))
    assert re.search(r"python:3\.12\.\d+-slim@sha256:[0-9a-f]{64}$", from_line), from_line


# ---------- lockfiles ----------

_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;\\]+)", re.M)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pins(path: Path) -> dict[str, str]:
    return {_norm(m[1]): m[2] for m in _PIN.finditer(path.read_text())}


@pytest.mark.parametrize("lock", ["runtime.lock", "dev.lock", "build.lock"])
def test_lockfiles_pin_and_hash_every_package(lock):
    text = (ROOT / "requirements" / lock).read_text()
    blocks = [b for b in re.split(r"\n(?=\S)", text) if _PIN.match(b)]
    assert blocks
    for block in blocks:
        assert "--hash=sha256:" in block, block.splitlines()[0]


def test_lockfiles_cover_declared_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    runtime, dev = _pins(ROOT / "requirements/runtime.lock"), _pins(ROOT / "requirements/dev.lock")
    for req in project["dependencies"]:
        assert _norm(re.split(r"[\[<>=!~ ]", req)[0]) in runtime, req
    for req in project["optional-dependencies"]["dev"]:
        assert _norm(re.split(r"[\[<>=!~ ]", req)[0]) in dev, req


def test_lockfiles_match_tested_environment():
    tested = _pins(ROOT / "requirements/tested-py314.txt")
    for lock in ("runtime.lock", "dev.lock"):
        for name, version in _pins(ROOT / "requirements" / lock).items():
            if name in tested:
                assert tested[name] == version, f"{lock}: {name} {version} != tested {tested[name]}"


def test_runtime_lock_is_subset_of_dev_lock():
    runtime, dev = _pins(ROOT / "requirements/runtime.lock"), _pins(ROOT / "requirements/dev.lock")
    assert {k: v for k, v in dev.items() if k in runtime} == runtime


def test_lockfiles_contain_no_machine_specific_paths():
    for lock in (ROOT / "requirements").iterdir():
        text = lock.read_text()
        assert "/tmp/" not in text and "/home/" not in text, lock.name
