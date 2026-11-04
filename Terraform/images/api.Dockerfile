FROM python:3.12.16-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MEL_PARTICIPANT_PACK_DIR=/data/participant-pack MEL_PRICING_FILE=/app/config/bedrock_pricing.json MEL_DATABASE_URL=sqlite:////app/var/mel.db
WORKDIR /app
COPY requirements/runtime.lock requirements/build.lock ./requirements/
RUN pip install --require-hashes -r requirements/runtime.lock && pip install --require-hashes -r requirements/build.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps --no-build-isolation . && pip check
COPY config ./config
COPY data/participant-pack /data/participant-pack
RUN mkdir -p /app/var && chown 10001:10001 /app/var
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["uvicorn","mel_agent.main:app","--host","127.0.0.1","--port","8000"]
