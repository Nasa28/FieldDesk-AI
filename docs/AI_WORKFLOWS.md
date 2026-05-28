# FieldDesk AI — AI Workflows

Every workflow below shares the same invariants:

- **Every provider call logs a row in `ai_model_calls`** (provider, model, tokens, duration, cost, success, error class).
- **Every job has a `(tenant_id, idempotency_key)` unique constraint.** Retries are safe.
- **No AI output is final.** Tickets stay in `draft` or `needs_review` until a human approves.
- **No cross-tenant data leaves a query.** All reads filter by `tenant_id`.

## 1. Transcription Workflow

Input: `voice_notes` row with an audio object in storage.
Output: `transcripts` row.

Steps:

1. Worker pulls the `transcribe` job.
2. Stream audio from object storage.
3. Reject non-retryable inputs (empty audio, unsupported mime, file too large).
4. Call transcription provider with a per-call timeout.
5. On success: insert `transcripts`, log `ai_model_calls`, enqueue `extract`.
6. On retryable error: bump `attempt_count`, set `retrying`, exponential backoff via `run_after`.
7. On exhausted retries: mark `voice_notes.status='failed'`, surface on the failures dashboard.

## 2. Extraction Workflow

Input: `transcripts` row.
Output: `ai_extractions` row + optional `job_tickets` draft.

Steps:

1. Build the prompt from the transcript + a versioned system prompt (`prompt_version`).
2. Call LLM with **structured output enforced** (provider-side JSON mode or tool-call schema). The schema is `TicketExtraction` in `apps/worker/fielddesk_worker/extraction/schema.py`.
3. Validate the response against the schema. If invalid → write `ai_extractions` with `json_valid=false`, route to `human_reviews` with reason `invalid_json`. Do **not** retry blindly — re-prompting is a separate, bounded path.
4. Compute confidence:
   - Required-field completion ratio.
   - Per-field confidence if the model reports it.
   - Heuristic checks (phone present, address parseable, etc.).
5. If `confidence < threshold` or required fields missing → `human_reviews` with reason `low_confidence` or `missing_fields`.
6. Otherwise: insert a `job_tickets` row with status `draft`.
7. Enqueue `rag` and `draft_ticket` jobs as needed.

## 3. RAG Workflow

Input: a draft `job_tickets` row.
Output: `rag_queries` row with top-k document chunks + metadata.

Steps:

1. Compose a query from `issue_summary` + `detailed_description` + `trade_type`.
2. Embed the query using the configured embedding model.
3. Hybrid retrieval (dense + lexical with RRF fusion) over `document_chunks` filtered by `tenant_id`.
4. Store results on `rag_queries.results` and link to the ticket.
5. Auto-enqueue a `draft_ticket` synthesis job (workflow §3a) keyed on the new rag_query id.
6. Surface retrieved chunks in the UI as "Related documents."

Ad-hoc knowledge-base queries use the same `rag` job without a ticket id.
`POST /v1/rag/search` returns retrieved passages in `ai_jobs.result`; `POST
/v1/rag/ask` also runs answer synthesis after retrieval and stores the
grounded answer under `ai_jobs.result.answer`.

## 3a. RAG Synthesis Workflow (Phase 4.5)

Input: a `job_tickets` row + the queued `rag_queries` row for that ticket.
Output: `ticket_recommendations` row with structured recs (possible diagnosis, suggested parts, safety checklist, follow-up questions, citations).

Steps:

1. Load ticket fields + the queued rag_query.results in one tenant-scoped query.
2. If retrieval returned zero chunks: insert a `ticket_recommendations` row with `insufficient_context=true`, no LLM call, no spend.
3. Otherwise, build a delimited prompt:
   - `system`: the `RECS_SYSTEM_PROMPT` (carries all output-format and safety rules).
   - `user`: ticket summary wrapped via `wrap_untrusted_ticket_summary`, then each chunk wrapped via `wrap_untrusted_chunk(chunk_id, text)` with HTML-escaped content and a sanitized chunk_id.
   - Cap per-chunk text at 1200 chars, limit to top 8 chunks. Defense-in-depth on top of retrieval's top-k.
4. Call the LLM provider's `complete_json` adapter; validate the JSON against `RecommendationsOutput`. Invalid JSON → persist a degraded row with `json_valid=false, insufficient_context=true` and the error.
5. Log one `ai_model_calls` row (kind=llm, purpose=recs_synthesis).
6. Surface in the UI as the "Suggestions" section on the ticket card.

The synthesis call is the highest-injection-risk LLM call in the system. The prompt explicitly tells the model that text inside `<ticket>` and `<chunk>` tags is data, never instructions, and golden cases in `evals/recommendations.py` verify that hostile ticket/chunk text cannot plant forbidden parts or override safety entries.

## 3b. Knowledge-Base Answer Workflow

Input: free-text user question.
Output: `ai_jobs.result.answer` with an answer, citations, confidence, and follow-up questions.

Steps:

1. Enqueue a `rag` job from `/v1/rag/ask` with `answer=true`.
2. Embed the question, run hybrid retrieval/rerank, and persist `rag_queries`.
3. If retrieval returned zero chunks: short-circuit with `insufficient_context=true`.
4. Otherwise, build a delimited prompt with the question wrapped as untrusted data and each chunk wrapped via `wrap_untrusted_chunk`.
5. Call the LLM provider's `complete_json` adapter; validate against `KnowledgeAnswerOutput`.
6. Drop citations that do not match retrieved chunk ids, log one `ai_model_calls` row with `purpose=kb_answer`, and return the answer through the existing AI job polling endpoint.

## 4. Confidence Scoring

Confidence is **not** the raw LLM token probability. It's a composite:

- 0.40 × required-field coverage (count of required fields filled / total required).
- 0.30 × self-reported confidence from the model (if available, else 0.5).
- 0.20 × heuristic validation passes (phone regex, address minimum length, etc.).
- 0.10 × transcription quality proxy (provider language confidence, audio duration plausibility).

`human_review_required` is set when:

- `confidence < 0.7`, OR
- any required field is missing, OR
- the transcript is shorter than a configured floor (likely garbled audio), OR
- any sensitive flag fires (safety concerns, customer dispute, warranty claim).

These thresholds are tunable per-tenant in `tenant_ai_budgets`-adjacent settings (future).

## 5. Human Review Workflow

1. Anything flagged is inserted into `human_reviews` with a `reason`.
2. Review queue UI shows the original transcript, the AI extraction, and the draft ticket side by side.
3. Reviewer edits fields → submit → API creates or patches a draft `job_tickets` row, records the diff in `human_reviews.correction`, and sets `resolved_at`.
4. Dispatcher approves or rejects the resulting draft ticket through the ticket API.
5. The correction is the ground truth used to compute the human correction rate eval.

## 6. Retry Workflow

- Strategy: exponential backoff with jitter. `delay = base * 2^attempt + rand(0, base)`.
- `base = 5s`, `max_attempts = 5` by default; both configurable per job type.
- Classification table (worker decides on each failure):
  - Retryable: `timeout`, `rate_limit`, `provider_5xx`, `network`, `worker_crash`.
  - Non-retryable: `invalid_input`, `tenant_mismatch`, `schema_invalid`, `not_found`.
- A retried attempt always writes a new `ai_job_attempts` row so the timeline is auditable.

## 7. Fallback Workflow

When a primary provider call fails:

1. Retry the **same model once** for transient errors.
2. If a backup model is configured for the kind (transcription / llm / embedding), switch and retry once.
3. If that fails too, mark the job `needs_review` and create a `human_reviews` row with reason `fallback`.

Fallback decisions are logged in `ai_jobs.result` for postmortem, including the model swap path.
