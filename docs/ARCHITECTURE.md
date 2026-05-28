# FieldDesk AI — Architecture

## 1. System Overview

FieldDesk AI is a three-service system with one shared database.

```
            ┌─────────────┐    HTTP    ┌─────────────┐
   user ──▶ │   Next.js   │ ─────────▶ │   Go API    │ ──▶ Postgres (pgvector)
            │   (web)     │            │   (chi)     │ ──▶ MinIO / S3
            └─────────────┘            └─────────────┘
                                              │
                                              │ enqueue (ai_jobs row)
                                              ▼
                                       ┌─────────────┐
                                       │   Python    │ ──▶ AI providers
                                       │   worker    │ ──▶ Postgres
                                       └─────────────┘
```

- **Go API** owns HTTP, auth, tenancy, validation, persistence, and job enqueueing.
- **Python worker** owns every AI provider call (transcription, LLM, embeddings).
- **Next.js web** is the dispatcher/admin UI.
- **Postgres** is the source of truth. The `ai_jobs` table is the queue.
- **MinIO** stands in for S3/R2 locally. Audio and document blobs live here.

## 2. Service Boundaries

| Concern                       | Owner   |
| ----------------------------- | ------- |
| Auth, tenancy, RBAC           | API     |
| HTTP routing, validation      | API     |
| Object storage presigning     | API     |
| Job enqueue + user-facing job reads | API     |
| Job execution status transitions    | Worker  |
| Provider calls (LLM, STT, emb)| Worker  |
| Cost + token accounting       | Worker writes, API reads |
| Eval runs                     | Worker  |
| UI, presentation              | Web     |

The API does **not** call AI providers directly. The worker does **not** expose
public HTTP. This boundary keeps secrets, retries, and cost accounting in one
place and makes the API trivially horizontally scalable.

### Shared Database Concurrency Contract

Direct Postgres access from both the API and worker is intentional. The safety
boundary is not "only one service can connect"; it is explicit row ownership,
tenant scope, and state-checked writes:

- API owns user commands: auth/session rows, upload confirmation, ticket edit /
  approve / reject, review resolution, and admin budget settings.
- Worker owns AI execution outputs: provider calls, transcripts, extractions,
  review insertion from failed AI steps, and job execution status.
- Every existing-row mutation on a shared table includes `tenant_id` and an
  expected state predicate. A stale command returns a conflict instead of
  overwriting newer work.
- Job execution uses `FOR UPDATE SKIP LOCKED` to claim work, then `locked_by` +
  `lease_expires_at` predicates to heartbeat, succeed, retry, or fail the job.
- Review resolution locks the `human_reviews` row and updates the linked
  `job_tickets` row only while it is still in an editable state.
- Shared calculations belong in SQL views, not duplicated service code. Budget
  enforcement and admin budget display both read `v_tenant_budget_usage`.

## 3. API Flow (request → response)

1. Web makes a request to `/v1/...` with auth + tenant context.
2. Chi router runs middleware: request id, logger, CORS, recoverer, tenant.
3. Handler validates input and calls a service.
4. Service uses sqlc-generated queries against Postgres.
5. For long-running work, service inserts an `ai_jobs` row (with idempotency key) and returns immediately.
6. Handler returns JSON.

## 4. AI Job Flow

```
voice_note upload ─▶ ai_jobs(transcribe) ─▶ transcripts
                                        └─▶ ai_jobs(extract) ─▶ ai_extractions
                                                              ├─▶ job_tickets (draft)
                                                              └─▶ ai_jobs(rag) ─▶ rag_queries
```

Each step:

1. Worker polls `ai_jobs WHERE status='pending' AND run_after <= now() ORDER BY run_after FOR UPDATE SKIP LOCKED`.
2. Marks the row `processing`, creates an `ai_job_attempts` row.
3. Runs the handler. Every provider call writes a row to `ai_model_calls`.
4. On success: updates result, sets `succeeded`, enqueues downstream jobs.
5. On retryable failure: increments `attempt_count`, sets `retrying`, schedules backoff via `run_after`.
6. On non-retryable failure or attempts exhausted: sets `failed` and inserts a `human_reviews` row when applicable.

## 5. Storage Flow

- Upload: API issues a presigned PUT URL. Web uploads directly to MinIO.
- Process: Worker reads via API-issued presigned GET or with its own credentials.
- Delete: only after document/voice note rows are deleted.

Object keys follow `tenants/<tenant_id>/voice-notes/<id>.<ext>` and
`tenants/<tenant_id>/documents/<id>/<filename>`.

## 6. RAG Flow

1. Document upload → `documents` row, `embed` job enqueued.
2. Worker chunks text → embeds each chunk → inserts `document_chunks` with `embedding vector(1536)`.
3. At ticket-draft time, worker builds a query string from extraction fields, embeds it, runs `ORDER BY embedding <=> :query_embedding LIMIT k` scoped by `tenant_id`.
4. Top-k results are stored on `rag_queries.results` and surfaced on the ticket.

All vector queries **must** filter by `tenant_id` first. Cross-tenant retrieval is a hard error.

## 7. Failure Handling

- Retryable: timeout, rate limit, transient provider error, network error, worker crash mid-flight.
- Non-retryable: unsupported file type, empty audio, invalid tenant, corrupt file, schema validation failure on extraction.
- Schema-validation failures on extraction route to `human_reviews` rather than retrying — the prompt is at fault, not the network.
- Idempotency: every job has `(tenant_id, idempotency_key)` unique. Re-enqueueing the same logical work returns the existing job id.
- Fallback: if a primary model fails after one same-model retry, the worker can route to a configured backup model. If all AI steps fail, the ticket goes to manual review.

## 8. Local Docker Setup

```
docker compose up -d postgres minio
docker compose run --rm migrate
docker compose up api worker web
```

URLs:

- Web: http://localhost:3000
- API: http://localhost:8080 (health: `/healthz`, ready: `/readyz`)
- MinIO console: http://localhost:9001 (user/pass `minioadmin`)
- Postgres: `localhost:5432` (`fielddesk` / `fielddesk`)

See `docs/AI_WORKFLOWS.md` for per-workflow detail.
