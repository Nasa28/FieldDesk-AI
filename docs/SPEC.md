# FieldDesk AI — Technical Spec

This is a living spec. Each section is intentionally minimal so the team can fill it in as it implements.

## 1. API Endpoints (v1)

Base path: `/v1`. All routes require a tenant context except `/healthz`, `/readyz`, and `/auth/{signup,login}`.

| Method | Path                              | Purpose                                                |
| ------ | --------------------------------- | ------------------------------------------------------ |
| GET    | `/healthz`                        | Liveness                                               |
| GET    | `/readyz`                         | Readiness (pings DB)                                   |
| POST   | `/auth/signup`                    | Create tenant + admin user                             |
| POST   | `/auth/login`                     | Issue session token                                    |
| POST   | `/auth/logout`                    | Invalidate session                                     |
| GET    | `/auth/me`                        | Current user + tenant                                  |
| GET    | `/voice-notes`                    | List voice notes for tenant                            |
| POST   | `/voice-notes`                    | Create voice-note row                                  |
| POST   | `/voice-notes/{id}/upload-url`    | Presigned PUT to MinIO/S3                              |
| GET    | `/voice-notes/{id}`               | Fetch voice note with transcript + tickets             |
| GET    | `/tickets`                        | List tickets                                           |
| GET    | `/tickets/{id}`                   | Fetch one ticket (with RAG suggestions)                |
| PATCH  | `/tickets/{id}`                   | Edit draft/needs_review/rejected ticket fields         |
| POST   | `/tickets/{id}/approve`           | Approve a draft → final                                |
| POST   | `/tickets/{id}/reject`            | Reject a draft/needs_review ticket                     |
| GET    | `/documents`                      | List uploaded knowledge documents                      |
| POST   | `/documents`                      | Create document + enqueue embedding job                |
| DELETE | `/documents/{id}`                 | Remove document + chunks                               |
| GET    | `/ai-jobs`                        | List jobs (filterable by status, type, time)           |
| GET    | `/ai-jobs/{id}`                   | Job detail + attempts                                  |
| POST   | `/ai-jobs/{id}/retry`             | Manually retry a failed job                            |
| GET    | `/model-logs`                     | Paginated `ai_model_calls` view                        |
| GET    | `/review-queue`                   | Open `human_reviews` rows                              |
| POST   | `/review-queue/{id}/resolve`      | Submit correction, mark resolved                       |
| GET    | `/admin/metrics`                  | Aggregate dashboard counters                           |
| GET    | `/admin/costs`                    | Cost rollups (today, month, per ticket, per model)     |
| GET    | `/admin/failures`                 | Failure summaries                                      |
| GET    | `/admin/budgets`                  | Read tenant budget                                     |
| PUT    | `/admin/budgets`                  | Update tenant budget                                   |

All write endpoints accept and validate a strict request schema. All list endpoints support `?limit=` and `?cursor=` pagination.

## 2. Database Schema Summary

Migrations live in `infra/migrations/` and run via Goose.

- `tenants`, `users` — workspace + auth.
- `voice_notes`, `transcripts` — audio + STT output.
- `job_tickets`, `ai_extractions` — drafts + structured extraction history.
- `ai_jobs`, `ai_job_attempts` — the work queue + attempt audit log.
- `ai_model_calls` — every provider call (cost, tokens, latency, success).
- `documents`, `document_chunks` — knowledge base; chunks have `vector(1536)` embeddings.
- `rag_queries` — retrieval results per ticket.
- `ticket_recommendations` — synthesized recs per retrieval (suggested parts, safety, follow-ups, citations).
- `human_reviews` — review queue + corrections.
- `ai_eval_cases`, `ai_eval_runs` — golden set + run results.
- `tenant_ai_budgets` — per-tenant cost limits.

Every row is scoped by `tenant_id`. All cross-row joins must filter on tenant id at the outermost level.

## 3. Background Jobs

Job types (see `apps/worker/fielddesk_worker/jobs/__init__.py`):

- `transcribe` — voice_note → transcript.
- `extract` — transcript → ai_extraction → ticket draft.
- `embed` — document → document_chunks.
- `rag` — ticket → rag_query.
- `draft_ticket` — ticket + rag_query → ticket_recommendations (RAG synthesis).

Job lifecycle: `pending → processing → (succeeded | failed | retrying | needs_review)`.

Queue mechanics:

- Polling via `SELECT ... FOR UPDATE SKIP LOCKED` on `ai_jobs`.
- Idempotency: unique on `(tenant_id, idempotency_key)`.
- Backoff stored in `run_after`; the poller picks rows where `run_after <= now()`.

## 4. Model Call Logging

Every provider call writes a row to `ai_model_calls`:

```json
{
  "kind": "llm",
  "provider": "openai",
  "model": "gpt-4o-mini",
  "input_tokens": 1234,
  "output_tokens": 211,
  "duration_ms": 845,
  "cost_usd": 0.00214,
  "success": true,
  "error_class": null,
  "request_meta": { "prompt_version": "extract.v3", "temperature": 0.0 }
}
```

The worker never makes a provider call without writing this row, even on failure.
Failed calls still cost money and must be visible.

## 5. Cost Tracking

- Cost is a NUMERIC(12,6) on `ai_model_calls`, `transcripts`, `ai_extractions`, `rag_queries`.
- Per-ticket cost: sum of all `ai_model_calls.cost_usd` where the job chain links back to the ticket's voice note.
- Per-tenant rollups computed in SQL views or scheduled aggregates (later); for MVP, on-demand SQL is fine.
- Budgets in `tenant_ai_budgets` are enforced at job-enqueue time:
  - If today's spend exceeds `daily_budget_usd` and `pause_on_exceeded` is true, new non-essential jobs are deferred and the admin is alerted.

## 6. Monitoring Events

Structured log events (slog/structlog JSON):

- `http_request` — method, path, status, duration, request_id.
- `job_pulled` — id, type, attempt.
- `job_succeeded` / `job_failed` — id, type, duration, error_class.
- `provider_call` — kind, provider, model, duration_ms, cost_usd, success.
- `schema_validation_failure` — extraction_id, prompt_version, error.
- `budget_threshold_crossed` — tenant_id, threshold, current_spend.

Future: ship to OpenTelemetry → Prometheus/Grafana. For MVP, JSON logs are enough.
