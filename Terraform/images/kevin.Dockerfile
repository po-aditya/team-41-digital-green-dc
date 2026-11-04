FROM python:3.12.16-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HOME=/tmp MEL_PACK_DIR=/data/participant-pack MEL_ALLOW_PAID_INFERENCE=false AWS_EC2_METADATA_DISABLED=true
WORKDIR /app/prototypes/kevin
COPY prototypes/kevin/requirements.txt /app/prototypes/kevin/requirements.txt
RUN pip install -r requirements.txt && pip check
COPY prototypes/kevin/mel_agent /app/prototypes/kevin/mel_agent
COPY prototypes/kevin/app /app/prototypes/kevin/app
COPY prototypes/kevin/reports /app/prototypes/kevin/reports
COPY prototypes/kevin/mockup /app/prototypes/kevin/mockup
COPY data/participant-pack /data/participant-pack
USER 10001
EXPOSE 8001 8501
CMD ["streamlit","run","app/streamlit_app.py","--server.address","0.0.0.0","--server.port","8501","--browser.gatherUsageStats","false"]
