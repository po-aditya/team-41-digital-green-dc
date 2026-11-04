# Python 3.12 runtime, pinned by digest for reproducible builds.
# Digest for python:3.12.16-slim (Debian trixie), looked up from Docker Hub on 2026-11-04.
# NOTE: this Dockerfile has not yet been built or run (no Docker on the dev machine).
FROM python:3.12.16-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # The participant pack is mounted read-only here (see docker-compose.yml).
    MEL_PARTICIPANT_PACK_DIR=/data/participant-pack \
    MEL_PRICING_FILE=/app/config/bedrock_pricing.json \
    MEL_DATABASE_URL=sqlite:////app/var/mel.db

WORKDIR /app

# 1. Exact, hash-checked third-party dependencies (cached layer).
COPY requirements/runtime.lock requirements/build.lock ./requirements/
RUN pip install --require-hashes -r requirements/runtime.lock \
 && pip install --require-hashes -r requirements/build.lock

# 2. The project itself, without re-resolving dependencies.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps --no-build-isolation . && pip check

COPY config ./config
RUN mkdir -p /app/var && useradd --create-home --uid 10001 app && chown -R app /app/var
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

CMD ["uvicorn", "mel_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
