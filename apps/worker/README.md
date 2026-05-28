# FieldDesk Worker

Python background worker for FieldDesk AI. Polls the `ai_jobs` table and
processes transcription, extraction, embedding, and RAG jobs.

## Run locally

```bash
cd apps/worker
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
fielddesk-worker
```

## Layout

- `fielddesk_worker/main.py` — entrypoint + polling loop.
- `fielddesk_worker/config.py` — settings loaded from env.
- `fielddesk_worker/db.py` — Postgres connection helper.
- `fielddesk_worker/jobs/` — job dispatch + per-type handlers.
- `fielddesk_worker/transcription/` — speech-to-text providers.
- `fielddesk_worker/extraction/` — structured JSON extraction.
- `fielddesk_worker/embeddings/` — embedding providers and chunking.
- `fielddesk_worker/rag/` — retrieval + context assembly.
- `fielddesk_worker/evals/` — golden-set runners and metric helpers.
- `fielddesk_worker/providers/` — thin adapters per AI provider.

All provider calls must be logged to `ai_model_calls` with tokens, latency,
cost, and error class. See `docs/AI_WORKFLOWS.md`.
