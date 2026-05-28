FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY apps/worker/pyproject.toml ./
COPY apps/worker/fielddesk_worker ./fielddesk_worker
COPY scripts/eval.sh ./scripts/eval.sh
RUN chmod +x ./scripts/eval.sh && pip install --upgrade pip && pip install .

CMD ["fielddesk-worker"]
