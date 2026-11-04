FROM python:3.12.16-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FARMERLOOP_PACK=/data/participant-pack AWS_EC2_METADATA_DISABLED=true
WORKDIR /app
COPY farmerloop/pyproject.toml farmerloop/README.md ./
COPY farmerloop/src ./src
RUN pip install . && pip check
COPY data/participant-pack /data/participant-pack
USER 10001
CMD ["python","-m","farmerloop.feedback_demo"]
