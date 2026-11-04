#!/usr/bin/env bash
# Regenerate the hashed lockfiles in requirements/.
#
# Needs uv (https://docs.astral.sh/uv/): `pipx install uv` or `pip install uv` in a
# separate tools environment, not the project venv.
#
# Versions are constrained to requirements/tested-py314.txt (the environment the
# test suite passed on), so re-locking does NOT upgrade anything. To upgrade on
# purpose: update the venv, re-run the tests, refresh tested-py314.txt with
#   .venv/bin/pip freeze --exclude-editable
# then run this script.
#
# The locks are "universal": one file valid for every Python >= 3.12 and platform.
set -euo pipefail
cd "$(dirname "$0")/.."
UV="${UV:-uv}"
COMMON=(--universal --python-version 3.12 --generate-hashes --no-header)

"$UV" pip compile pyproject.toml "${COMMON[@]}" -c requirements/tested-py314.txt -o requirements/runtime.lock
"$UV" pip compile pyproject.toml --extra dev "${COMMON[@]}" -c requirements/tested-py314.txt -o requirements/dev.lock
# Build backend (pyproject.toml [build-system]); pinned so re-locking never upgrades it.
printf 'setuptools==84.2.1\n' | "$UV" pip compile - "${COMMON[@]}" -o requirements/build.lock
echo "Locked: requirements/runtime.lock, requirements/dev.lock, requirements/build.lock"
