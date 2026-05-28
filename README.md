# FieldDesk AI

A voice-to-ticket system for field service teams. Technicians upload voice notes;
FieldDesk transcribes them, extracts structured ticket fields, retrieves relevant
company knowledge via RAG, drafts a ticket, and routes uncertain output to human
review. Every model call is logged with cost, tokens, latency, and success.

This repo is built as an applied-AI portfolio project. The goal is not "a demo
that works"; it is "a system you would be unembarrassed to put in front of a
production team." See `docs/PRD.md` and `AGENTS.md` for the rules of the road.

## Status

**Phase 5 (prompt-version comparison) implemented.** Closes PRD §19's last
bullet. Extraction prompts now live in a versioned registry at
[apps/worker/fielddesk_worker/prompts/extraction.py](fielddesk-ai/apps/worker/fielddesk_worker/prompts/extraction.py)
with a `get_extraction_prompt(version)` lookup and a SHA-256-based
`extraction_prompt_hash(version)` so drifted "frozen" versions surface in
the eval metrics. v1 is the production prompt (the injection-hardened
body that was inline in `openai_llm.py`); v2 is a deliberate ablation that
omits the explicit "ignore transcript instructions" rule — kept around so
the comparison feature has a known-worse baseline to demonstrate against.

The eval CLI grew a `--compare` flag:

```bash
python -m fielddesk_worker.evals --tenant <uuid> --kind extraction \
    --compare extract.v1.injection-hardened,extract.v2.ablation
```

The runner executes the same golden injection cases under each version,
writes one `ai_eval_runs` row per version (`prompt_version` set
correctly), and prints a side-by-side table on stderr:

```text
version                                hash             inj_resist    delta  cases    sec
-----------------------------------------------------------------------------------------
extract.v1.injection-hardened          a3f9b2c1...          0.967     base       3    8.4
extract.v2.ablation                    7e0c5d18...          0.333   -0.633       3    8.1
REGRESSION: at least one non-baseline version scored worse than baseline.
```

`--regression-threshold 0.05` tolerates a 5-point drop before flagging a
regression (useful when v2 is intentionally trading some safety for
terseness). The first version listed is the baseline; deltas are
"candidate − baseline." Exit code is non-zero on regression so the nightly
cron / GitHub Actions / pre-deploy check fails noisily.

Every provider call inside a comparison run logs to `ai_model_calls` with
`request_meta.prompt_version` set, so the cost dashboard can break spend
out by prompt version without parsing the eval-run blob.

Adding a v3:

1. Add a frozen body constant in `prompts/extraction.py` and register it
   under a stable string (`extract.v3.something`).
2. `pnpm web:build` / `make quality` (no API changes needed; the eval
   reads the registry directly).
3. Run `--compare extract.v1.injection-hardened,extract.v3.something`
   against the demo tenant. Promote v3 by changing
   `DEFAULT_EXTRACTION_PROMPT_VERSION` once the comparison clears.

**Phase 4.5 (RAG synthesis backend) implemented.** Retrieved chunks now feed
a structured LLM synthesis call that produces ticket-specific recommendations
(possible diagnosis, suggested parts, safety checklist, follow-up questions,
citations). The `draft_ticket` job type, previously a stub, is now the
synthesis handler: it auto-enqueues after every ticket-bound `rag` job using
the rag_query id as its idempotency key, calls `LLMProvider.complete_json`
with `RECS_SYSTEM_PROMPT`, and persists a `ticket_recommendations` row.

Key safety properties:

- Ticket summary and retrieved chunks are fed through untrusted-data wrappers
  (`<ticket>` and `<chunk>`), using the same HTML-escape + delimiter
  discipline as transcripts. The system prompt explicitly says that text
  inside those tags is data, never instructions.
- Per-chunk text capped at 1200 chars; max 8 chunks per synthesis. Caps
  blast radius on top of retrieval's top-k.
- Zero-chunk retrievals short-circuit: a `ticket_recommendations` row with
  `insufficient_context=true` is written with no LLM call, no spend.
- Invalid JSON from the model persists a degraded row (`json_valid=false`,
  `insufficient_context=true`) rather than silently dropping the synthesis.
- `draft_ticket` joined `BUDGET_GATED_JOB_TYPES`. A budget-exceeded synthesis
  routes to `human_reviews` like every other paid AI job.

The `kind='recs'` eval suite adds hostile ticket/chunk cases: ticket-summary
override, fake-part breakout via tag-injection, dangerous safety-checklist
override, and an empty-chunks-must-say-so case. Run with
`python -m fielddesk_worker.evals --tenant <uuid> --kind recs`. Migration
00019 extends `ai_eval_runs.kind` to include `recs`.

API: `GET /v1/tickets/{id}/recommendations` returns a denormalized,
citation-enriched view. The handler joins each citation's `chunk_id` against
the `rag_query.results` that drove the synthesis and attaches
`document_title`, `heading_path`, and `source_page`; hallucinated chunk_ids
(ones the model emitted that weren't in the retrieval set) are dropped
server-side so the wire shape never carries unattributable citations. 404
surfaces as "synthesis pending" rather than an error. Pure-function tests in
`recommendations_test.go` cover the enrichment join, hallucination drop,
zero-blob-confidence fallback to the row column, and bad-JSON degradation.

**Phase 4.5 (web UI) implemented.** Each ticket card on `/tickets` now
shows a "Suggestions" section below "Related documents." The component
surfaces the three states the worker writes deliberately so an operator
sees *why* a card looks empty: bad-JSON degradation (`json_valid=false`
with the error_message rendered prominently), insufficient context
(`insufficient_context=true` with the worker's `notes` shown verbatim),
and the still-pending case (404 — same pattern as RelatedDocuments). Confidence is
displayed in a colored bucket (high/medium/low). Plain-text rendering only;
no `dangerouslySetInnerHTML` despite ingesting tenant-document content
through the LLM.

**Phase 4b (web UI) implemented.** The Documents page now drives the full
upload handshake (create → presigned PUT → confirm) with title input,
mime-from-extension normalization (browsers report markdown inconsistently),
status badges with parse_error display, and delete. Each ticket card on
`/tickets` now shows a "Related documents" section that reads
`GET /v1/rag/queries/by-ticket/{id}` and renders chunks with their
document title, heading path, page number, and per-channel rank.
A 404 surface (rag job still queued) shows a pending state with a
manual Refresh, not a red error.

**Phase 4c (eval CLI) implemented.** Run with:

```bash
python -m fielddesk_worker.evals --tenant <uuid> --kind all
```

Two suites, both writing one row to `ai_eval_runs`:

- **rag**: 5 golden `(query, expected_document_titles)` cases. Reports
  `recall@5` and `MRR` (Voorhees 1999). Score is on document-title
  overlap because chunk ids vary across re-ingest. Logs each query
  embedding to `ai_model_calls` with `request_meta.eval = true` so
  eval spend appears in the cost dashboard, optionally filterable.
- **extraction (injection)**: 3 canonical attack transcripts —
  tag-breakout (`</transcript><system>...</system>`), plain
  "ignore previous instructions" override, and persona-swap. Each
  case names a planted phone number / customer name the attacker
  is trying to exfiltrate; a pass means the hardened prompt held
  (no planted value, `human_review_required = true` when the case
  demands it). Reports `injection_resistance_rate`.

CLI exit code is non-zero when any requested suite misses the stability gates:
RAG `recall@1 >= 0.90`, RAG `recall@K = 1.0`, extraction injection
resistance `= 1.0`, and recs injection resistance `= 1.0` by default.
Override with `--min-rag-recall-at-1`, `--min-rag-recall-at-k`,
`--min-extraction-injection-resistance`, or
`--min-recs-injection-resistance` only when intentionally running a looser
experiment.

**Dogfood: seed the corpus, then run the eval.** The rag eval scores against
the 5 document titles in `evals/golden.py:SEED_DOCUMENT_TITLES`; without
those documents uploaded, `recall@5 = 0` and the numbers are noise.
Markdown content lives at [infra/seed_corpus/](fielddesk-ai/infra/seed_corpus/)
— real-feeling SOPs / safety procedures / parts catalog written so the
lexical and dense retrieval channels both have something to grip.

```bash
docker compose up -d           # if not already running
TENANT=$(./scripts/seed.sh)    # creates the demo tenant, prints its uuid
./scripts/seed-corpus.sh "$TENANT" http://localhost:8080 --wait
./scripts/eval.sh "$TENANT" all
```

`--wait` polls until every document hits `status='ready'` (or `failed`) so
the eval doesn't race the embed jobs. Without it, the script returns right
after enqueueing and you have to wait ~10-30 seconds yourself.

**Measured baseline (live OpenAI `text-embedding-3-small`, n=12, 2026-05-28):**

| metric | hybrid_search only | + Voyage rerank-2.5-lite |
| --- | --- | --- |
| `recall@1` | 0.917 | **1.000** |
| `recall@3` | 1.000 | 1.000 |
| `recall@5` | 1.000 | 1.000 |
| `MRR` | 0.958 | **1.000** |

`recall@5` is structurally saturated whenever `corpus_size <= top_k` —
every case can find its doc somewhere in the returned list, so the
discriminating metric on this corpus is `recall@1`.

**Rerank fixed the stubborn case.** Without rerank, `rag.warranty.paraphrase_solder_redo`
(asking about a soldered joint that started leaking a year later) lands
at rank 2 — the Parts Catalog's tight "Lead-free solder, 1/2 lb roll"
chunk out-competes the warranty doc's "Lifetime on workmanship defects
— if a joint we soldered fails…" sentence, which is buried in a longer
warranty paragraph and has weaker chunk-level vector similarity. Voyage
rerank-2.5-lite, given the full chunk text and query together, correctly
ranks the warranty chunk at 1 (relevance score 0.78 vs 0.45 for the
runner-up). Total rerank cost for all 12 cases: ~$0.0006 (well inside
Voyage's 200M-token free tier).

**Two real bugs were caught during this measurement and worth flagging:**

1. The rerank helper initially read the wrong dict key (`chunk_text` vs
   the actual SQL column `text`), so for several runs the reranker was
   silently scoring empty strings. Single-character fix in
   [retrieval.py](fielddesk-ai/apps/worker/fielddesk_worker/rag/retrieval.py)
   plus a comment so it doesn't recur. Lesson: when a measured
   intervention produces *identical* numbers, suspect a wiring bug
   before suspecting null result.

2. Voyage's free tier (no payment method on file) caps at 3 RPM, which
   the 12-case eval blew through in ~15 seconds — 9 of 12 calls returned
   429 and silently degraded to hybrid_search ordering. Added tenacity
   exponential-backoff retry (4s/8s/16s/32s, max 4 attempts) in
   [voyage.py](fielddesk-ai/apps/worker/fielddesk_worker/reranking/voyage.py)
   so the eval works on free tier (slow — ~4 min) and production stays
   robust against the same shape of 429 from any provider.

The golden set has three categories (n=12 total):

- **direct** (n=5) — queries reuse vocabulary from the doc; lexical
  channel carries the load.
- **paraphrase** (n=5) — query and doc share almost no words; dense
  channel has to do real semantic work.
- **cross-topic** (n=2) — query legitimately involves two docs; the
  *primary* doc with the actual answer is expected to rank highest.

Embedding spend for the full dogfood (5 docs + 12 queries) was ~150
input tokens. Sub-cent at quoted prices.

Honest gap: a production benchmark would broaden the corpus past 5
docs and add negative-case queries (test that low-relevance queries
return low-confidence retrieval rather than confident garbage). The
retrieval scorer doesn't surface a confidence threshold to the eval
yet — adding it is a separate slice.

Contextual retrieval is now implemented as deterministic metadata context
at ingest: the worker stores raw `text` for citations/UI, stores
`retrieval_text` for search, embeds `retrieval_text`, and builds the
lexical `text_search` column from it. Existing corpora need migration
00023 plus re-ingest to get contextual embeddings; until re-ingested,
legacy rows keep `retrieval_text = text`.

Before any of that hits a live stack, [test_seed_corpus.py](fielddesk-ai/apps/worker/tests/test_seed_corpus.py)
exercises the parser + chunker against each markdown file (no DB, no
OpenAI): every doc must parse into multiple segments, carry heading paths
that survive chunking, and produce unique content hashes per chunk. If the
content_hash check trips, the partial UNIQUE on (document_id, content_hash)
would silently drop chunks at insert time and the operator would lose
content without an error.

**Two ways to run the eval on a schedule:**

1. **Docker-compose sidecar** — opt-in via the `evals` profile so the
   default stack doesn't burn API credits on every `up`:

   ```bash
   # Set in .env first: EVALS_TENANT_ID=<uuid>, EVALS_INTERVAL_SECONDS=86400
   docker compose --profile evals up -d evals
   docker compose logs -f evals   # watch a run
   ```

   The sidecar reuses the worker image, sleeps `EVALS_INTERVAL_SECONDS`
   between runs, and `|| true`s a single failed eval so a transient
   OpenAI 5xx doesn't pull docker into its restart-backoff. Runtime failures
   still land in `ai_eval_runs` with `passed=0` when Postgres is reachable.
2. **Host crontab** — see [infra/cron/evals.crontab](infra/cron/evals.crontab)
   for the template. Defaults to 03:17 UTC nightly (deliberately off-the-
   hour to avoid the synchronized-cron rate-limit spike). MAILTO catches
   the non-zero exit so a regression actually surfaces.

Either path runs [scripts/eval.sh](scripts/eval.sh), the wrapper
around the CLI. On a host checkout it uses `apps/worker/.venv/bin/python` when
that venv exists; inside Docker it uses the installed worker package.

**Shared prompt-safety helpers.**
[apps/worker/fielddesk_worker/prompting/safety.py](apps/worker/fielddesk_worker/prompting/safety.py)
now centralizes `wrap_untrusted_transcript` and `wrap_untrusted_chunk(id, text)`.
The extraction provider was refactored to use the shared transcript wrapper.
The chunk wrapper is in place ahead of the RAG synthesis layer (Phase 4.5) so
synthesis prompts inherit the same HTML-escape + delimiter discipline AGENTS.md
mandates. Hostile chunk ids get replaced wholesale with underscores rather than
partial substitution, to prevent attribute-escape attacks. 8 tests cover the
canonical injection payloads for both transcripts and chunks.

**Phase 4 (RAG) backend implemented.** Documents now upload, parse, chunk,
embed, and search end-to-end via a hybrid (dense + lexical) retrieval
recipe grounded in mid-2026 production practice.

- **Upload + ingest**: `POST /v1/documents` mirrors the voice-notes flow
  (create row → presigned PUT → confirm). Supported formats: `.txt`,
  `.md`, `.pdf` (text-native and scanned — scanned falls back to OCR
  automatically), `.docx`, `.pptx`, `.doc`. Encrypted PDFs land as
  `failed` with an actionable `parse_error` asking the operator to
  re-upload an unencrypted copy.
- **Parsing** (`apps/worker/fielddesk_worker/parsing/`): heading-aware for
  markdown and DOCX, per-page for PDF (citations carry `source_page`),
  per-slide for PPTX (citations carry `source_locator.slide`), text
  fallback. Scanned PDFs route through `pypdfium2` (in-process page
  rendering, no poppler dep) + Tesseract OCR; OCR'd segments carry
  `source_locator.ocr=true` so confidence can be modulated on
  scan-derived text. `.doc` goes through a headless LibreOffice
  subprocess (`soffice --headless --convert-to docx`) and then the
  existing DOCX parser, so heading_path + table handling stay
  identical to a native `.docx` upload. Each parser emits
  `ParsedSegment(text, heading_path, source_page, source_locator)`.
- **Chunking**: token-aware via `tiktoken` (cl100k_base), 512 tokens
  target / 64 tokens overlap, recursive split on `\n\n` → `\n` →
  sentence boundaries → hard token cut as last resort. Idempotent via
  SHA-256 `content_hash` (text + heading_path + source_page) with a
  partial `UNIQUE` index so re-ingest doesn't duplicate.
- **Embeddings**: pluggable provider — `text-embedding-3-small` by
  default (`text-embedding-3-large` is one config flip away).
  Halfvec(1536) column with HNSW (`m=16, ef_construction=200`); old
  `vector(1536)` + IVFFlat from migration 00007 is replaced in 00017.
  The embedding input is `retrieval_text`: a deterministic prefix with
  document title, heading path, page, and slide context followed by the
  raw chunk.
- **Hybrid retrieval**: single SQL CTE in
  `apps/api/internal/database/rag.go` + `apps/worker/.../db_queries/rag.py`
  — dense (cosine) + lexical (`tsvector` + `ts_rank_cd`) fused with RRF
  (k=60), tenant-scoped at the outer `WHERE`. The lexical channel indexes
  `retrieval_text`; results still return raw `text` for citations. Returns
  top-K with `chunk_id`, `document_title`, `heading_path`, `source_page`,
  `dense_rank`, `lexical_rank`, `fused_score`.
- **Ad-hoc search / ask**: `POST /v1/rag/search` enqueues retrieval only;
  `POST /v1/rag/ask` enqueues retrieval plus grounded answer synthesis.
  Both return 202 + `job_id`; clients poll `/v1/ai-jobs/{id}`. Results land
  in `ai_jobs.result` and `rag_queries`. The Go API deliberately holds no
  provider keys — keeps the boundary that worker = AI, API = HTTP/DB.
- **Auto-suggest on tickets**: when extraction creates a `job_ticket`,
  a `rag` job is enqueued (idempotency: `rag:ticket:<id>`). The ticket
  page reads it via `GET /v1/rag/queries/by-ticket/{id}`.
- **Cost + budget enforcement**: embeddings are gated by the existing
  Phase 3 budget pre-flight (`embed` is in `BUDGET_GATED_JOB_TYPES`).
  Cost lands in `ai_model_calls` with `kind='embedding'`.

**Post-Phase-4 status / still deferred**:

- Reranking is implemented as an optional Cohere/Voyage pass after
  hybrid search; Voyage `rerank-2.5-lite` took the 12-case seed eval to
  `recall@1 = 1.000`.
- Contextual retrieval is implemented without adding an ingest-time LLM
  dependency: deterministic metadata context is embedded and lexically
  indexed, while raw chunks remain the citation surface.
- Encrypted PDF unlocking (we detect + surface an actionable error,
  but don't accept passwords; operators must re-upload an unencrypted
  copy). Structured table extraction (cell-coordinate-preserving) still
  out of scope.
- Indirect prompt-injection mitigation for future RAG synthesis. Retrieved
  chunks are storage/UI-only today; before any LLM synthesis layer ships
  (Phase 4.5), chunk prompts must use untrusted-content delimiters and
  citation requirements.

**Phase 3 bullet 5 (tenant budgets) implemented.**
`PUT /v1/admin/budgets` upserts the tenant's daily / monthly / per-ticket
caps + `pause_on_exceeded` toggle. `GET /v1/admin/budgets` returns the
current limits together with today's spend, month-to-date spend, and the
`daily_over` / `monthly_over` flags computed by a Postgres view
(`v_tenant_budget_usage`). Both the Go API and the Python worker read
from the same view so the math can't drift.

Enforcement runs in the worker as a **pre-flight check**: right after
`_claim_next_job` claims a job, `_budget_blocked` reads the view; if the
tenant is over budget AND `pause_on_exceeded = true`, the job is routed
to `needs_review` with `error_class = 'budget_exceeded'` and a
`human_reviews` row with `reason = 'budget_exceeded'`. No provider call
is made, so no spend is incurred. Existing unified failure feed at
`/admin/failures` surfaces the blocked job automatically.

`draft_ticket` jobs are exempt (no provider call → no spend). The PRD's
`max_cost_per_ticket` cap is still deferred for the same reason
"most expensive tickets" is — it needs a denormalized `job_ticket_id`
column on `ai_model_calls`, or the JSONB-join chain.

**Phase 3b implemented.** The web dashboard now consumes the Phase 3a
admin endpoints. `/settings` is the canonical place to set the tenant ID
(persisted to `localStorage`, attached as `X-Tenant-ID` on every request).
`/costs` shows the rollup card (total / successful / failed cost split),
per-kind table, and per-provider/model table. `/ai-logs` is the raw
provider-call feed with filters (kind, provider, success) and cursor
pagination. `/failures` is the same shape, scoped to `success = false`,
with a running "failed cost (loaded rows)" indicator at the top. All
three pages share `lib/dashboard.ts` for window defaults, USD formatting,
and RFC3339 conversion. Tables, not charts — charts are a follow-up.

**Phase 3a implemented.** Cost and observability endpoints are live on the
API. `GET /v1/admin/costs` returns a tenant-scoped cost rollup over a time
window (total, successful, and explicitly failed cost separated, plus
per-`kind` and per-`provider`/`model` breakdowns). `GET /v1/admin/metrics`
returns `ai_jobs` counters by status, a retry rate, a success/failure rate
over terminal jobs, and `percentile_cont` p50/p95 latency per `kind`. `GET
/v1/admin/failures` and `GET /v1/model-logs` paginate raw `ai_model_calls`
rows with cursor pagination and optional `kind` / `provider` / `success`
filters. Every query filters by `tenant_id` at the outer `WHERE` (the
`scripts/check-tenant-filter.py` gate enforces this).

**Deferred from Phase 3** (named, not dropped):

- "Most expensive tickets" and "avg cost per ticket" — need the JSONB
  join chain `ai_model_calls.job_id → ai_jobs.payload->>'voice_note_id'
  → job_tickets.voice_note_id`. Will denormalize a `job_ticket_id`
  column on `ai_model_calls` when Phase 4 (RAG) adds more cost rows
  worth attributing per-ticket.
- `max_cost_per_ticket` cap — same dependency.
- "Cost by user" — needs real auth.
- Slack / email alerts when budget approached — separate slice; we
  don't have a notifications channel yet.
- Model routing (cheap vs. strong by task / confidence) — different
  lever; not budget enforcement.
- Charts. Tables first.

**Phase 1 + 2 (prior status).** Voice → transcribe → extract → human
review → approve/reject is end-to-end. `GET /v1/review-queue` returns
open reviews enriched with the linked voice note, transcript, AI
extraction, and draft ticket. `POST /v1/review-queue/{id}/resolve` accepts
a `correction` payload, creates or updates a draft `job_tickets` row in the
same transaction, and marks the review `resolved`. `POST
/v1/tickets/{id}/approve` and `.../reject` finalize the ticket. RAG,
document upload, real auth, and the web UI remain placeholders.

## Layout

```
fielddesk-ai/
├── apps/
│   ├── api/          # Go (chi) HTTP API, sqlc, Goose
│   ├── worker/       # Python AI worker (transcription / extraction / RAG)
│   └── web/          # Next.js dashboard
├── docs/             # PRD, architecture, AI workflows, evals, spec
├── infra/
│   ├── migrations/   # Goose SQL migrations
│   └── docker/       # Dockerfiles for each service
├── scripts/          # migrate.sh, seed.sh
├── docker-compose.yml
├── .env.example
└── AGENTS.md
```

## Local Setup

Prerequisites:

- Docker + Docker Compose
- (Optional, for local dev outside Docker) Go 1.22, Python 3.11+, Node 20+, `goose` CLI

Bring up the full stack:

```bash
cp .env.example .env
# (Optional) fill in OPENAI_API_KEY / ANTHROPIC_API_KEY for real AI calls.

docker compose up --build
```

Compose waits for Postgres + MinIO to be healthy, then runs `migrate` (Goose)
and `createbuckets` (MinIO) to completion, then starts `api`, `worker`, and `web`.

Stop everything:

```bash
docker compose down
```

Wipe local state (volumes too):

```bash
docker compose down -v
```

## Service URLs

| Service        | URL                          | Notes                              |
| -------------- | ---------------------------- | ---------------------------------- |
| Web            | http://localhost:3000        | Next.js dashboard                  |
| API            | http://localhost:8080        | Go service                         |
| API health     | http://localhost:8080/healthz| Liveness                           |
| API ready      | http://localhost:8080/readyz | Pings Postgres                     |
| MinIO console  | http://localhost:9001        | user/pass: `minioadmin/minioadmin` |
| MinIO S3 API   | http://localhost:9000        |                                    |
| Postgres       | localhost:5432               | `fielddesk` / `fielddesk`          |

## Environment Variables

All variables documented in [.env.example](.env.example). The important ones:

- `DATABASE_URL` — Postgres DSN used by API, worker, and Goose.
- `S3_ENDPOINT` — in-cluster MinIO/S3 host (`minio:9000` in Compose).
- `S3_PUBLIC_ENDPOINT` — host-visible URL the **browser/client** can reach (e.g. `http://localhost:9000`). Presigned URLs are rewritten to use this.
- `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_USE_SSL` — standard S3 creds.
- `VOICE_NOTE_MAX_BYTES` — server-side upload size cap (default 50 MiB).
- `PRESIGN_TTL_SECONDS` — how long a presigned PUT URL is valid (default 900).
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` — provider keys for the worker.
- `TRANSCRIPTION_PROVIDER` / `LLM_PROVIDER` / `EMBEDDING_PROVIDER` — provider routing.
- `WORKER_*` — poll interval, concurrency, max retries.

## Transcription providers

Selected per-tenant via two env vars:

- `TRANSCRIPTION_PROVIDER` — `stub` (default) or `openai`.
- `TRANSCRIPTION_MODEL` — provider-specific. Defaults to `whisper-1` for OpenAI; ignored by stub.

### Stub mode (default)

```bash
TRANSCRIPTION_PROVIDER=stub
```

The worker reads the audio bytes from MinIO (so the round-trip is still
exercised), then returns a fixed fake transcript. Persists:

- `transcripts` row with `provider=stub`, `model=stub-transcriber-v1`, `cost_usd=0`.
- `ai_model_calls` row with `kind=transcription`, `provider=stub`, `success=t`, `cost_usd=0`.

No external network calls, no API key required.

### OpenAI mode

```bash
TRANSCRIPTION_PROVIDER=openai
TRANSCRIPTION_MODEL=whisper-1
OPENAI_API_KEY=sk-...
```

The worker `GET`s the object from MinIO, POSTs it as multipart to
`https://api.openai.com/v1/audio/transcriptions` with `response_format=verbose_json`,
and records:

- `transcripts.text` — the real transcript.
- `transcripts.language` — language detected by Whisper (e.g. `english`).
- `transcripts.provider=openai`, `transcripts.model=whisper-1`.
- `transcripts.duration_ms` — wall-clock time of the API call.
- `transcripts.cost_usd` — estimated from `audio_duration_sec * (0.006 / 60)` for `whisper-1`. The audio duration comes from Whisper's `verbose_json` response.
- `ai_model_calls` row with the same provider/model/duration/cost and `success=true`.

### Cost tracking

Every transcription, success or failure, writes an `ai_model_calls` row. The
`cost_usd` column is the source of truth for billing. Aggregate per tenant /
per month / per ticket with a SQL `SUM(cost_usd)` query. Failed provider
calls write `success=false` rows from a separate connection so they survive
the per-job savepoint rollback — failed transcribe attempts still show up
in cost reports as `cost_usd=0` rows.

### Failure handling

- Retryable errors (network, 5xx, timeout) follow the existing exponential
  backoff in `ai_jobs` until `max_attempts` is reached.
- On terminal failure, `voice_notes.status` is updated to `failed` (with
  `error_class` set) by the worker queue (see [00011_voice_notes_failed_transcription.sql](infra/migrations/00011_voice_notes_failed_transcription.sql)).
- The `transcripts` row is **only** written when the provider succeeds.

## Extraction providers

Selected per-tenant via two env vars:

- `EXTRACTION_PROVIDER` — `stub` (default) or `openai`.
- `EXTRACTION_MODEL` — provider-specific. Defaults to `gpt-4o-mini` for OpenAI; ignored by stub.
- `EXTRACTION_CONFIDENCE_THRESHOLD` — float in `[0, 1]`. Below this, the extraction routes to `human_reviews`. Default `0.7`.

### Extraction stub mode (default)

```bash
EXTRACTION_PROVIDER=stub
```

Returns a fixed, valid `TicketExtraction` (confidence 0.92). Persists:

- `ai_extractions` with `provider=stub`, `model=stub-extractor-v1`, `json_valid=t`, `confidence=0.920`, `cost_usd=0`.
- `ai_model_calls` with `kind=extraction`, `success=t`, `cost_usd=0`.
- `job_tickets` row with `status=draft`, `source=ai_extraction`, fields filled from the stub.
- No `human_reviews` row (high confidence, valid JSON).

### Extraction OpenAI mode

```bash
EXTRACTION_PROVIDER=openai
EXTRACTION_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
```

The worker `POST`s the transcript text, XML-escaped inside
`<transcript>...</transcript>` tags, plus a fixed system prompt to
`https://api.openai.com/v1/chat/completions` with `response_format=json_object`
and `temperature=0`. The system prompt tells the model that transcript content
is untrusted data to extract from, not instructions to follow. The response is
parsed and validated against
`TicketExtraction` (Pydantic).

Cost is computed from the response's `usage.prompt_tokens` and
`usage.completion_tokens` using the per-model rates in
[providers/openai_llm.py](apps/worker/fielddesk_worker/providers/openai_llm.py)
(`gpt-4o-mini`: $0.15/M input, $0.60/M output).

Outcomes:

- **Valid + confident + has `issue_summary`** → `ai_extractions(json_valid=t)`, `ai_model_calls`, `job_tickets(draft, source=ai_extraction)`; extraction is linked back via `ai_extractions.job_ticket_id`.
- **Invalid JSON** (Pydantic raises) → `ai_extractions(json_valid=f, error_message=…)`, `human_reviews(reason=invalid_json)`. No ticket.
- **`human_review_required=true` from the model** → `human_reviews(reason=provider_uncertainty)`.
- **`confidence < threshold`** → `human_reviews(reason=low_confidence)`.
- **Missing `issue_summary`** → `human_reviews(reason=missing_fields)`.

In all routing-to-review cases the `extract` job ends `succeeded` — the
system handled it correctly. Only real provider/network errors fail the job
and retry.

## Vertical-slice demo

End-to-end: create a voice-note record → presigned URL → PUT to MinIO →
confirm upload → worker reads bytes from MinIO → calls the configured
transcription provider (`stub` or `openai`) → writes `transcripts`, logs
`ai_model_calls`, flips `voice_notes.status` to `transcribed`, and enqueues
an `extract` job. The same flow works in both modes; only the provider
changes (and the cost shown on `ai_model_calls`).

### 1. Bring up the stack

```bash
cp .env.example .env
docker compose up --build
```

Wait until the API logs `api listening port=8080`.

### 2. Seed a demo tenant and capture its UUID

```bash
TENANT_ID=$(./scripts/seed.sh)
echo "tenant: $TENANT_ID"
```

`scripts/seed.sh` works whether or not you have a local `psql` — it falls back
to `docker compose exec postgres`. It prints just the tenant UUID on stdout.

### 3. Create a voice-note record

```bash
AUDIO=/path/to/note.mp3
SIZE=$(wc -c < "$AUDIO" | tr -d ' ')

VN_ID=$(curl -sS -X POST http://localhost:8080/v1/voice-notes \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: $TENANT_ID" \
  -d "{\"filename\":\"$(basename "$AUDIO")\",\"mime_type\":\"audio/mpeg\",\"size_bytes\":$SIZE}" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "voice_note: $VN_ID"
```

HTTP 201, status `pending_upload`.

### 4. Request a presigned upload URL

```bash
UPLOAD_URL=$(curl -sS -X POST "http://localhost:8080/v1/voice-notes/$VN_ID/upload-url" \
  -H "X-Tenant-ID: $TENANT_ID" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["upload_url"])')
```

This now returns *only* the URL info — no job is enqueued yet.

### 5. PUT the audio to MinIO

```bash
curl -sS -X PUT "$UPLOAD_URL" \
  -H "Content-Type: audio/mpeg" \
  --data-binary "@$AUDIO" -o /dev/null -w "HTTP %{http_code}\n"
```

Expect `HTTP 200`. The object appears in the MinIO console at <http://localhost:9001>.

### 6. Confirm the upload (this is the new step — enqueues `transcribe`)

```bash
curl -sS -X POST "http://localhost:8080/v1/voice-notes/$VN_ID/uploaded" \
  -H "X-Tenant-ID: $TENANT_ID" | python3 -m json.tool
```

The API does a server-side `StatObject` on MinIO. If the object is missing
you get `409 not_uploaded`; otherwise the response includes the updated
voice note (`status: uploaded`) and the newly enqueued job.

### 7. Watch the worker pick it up

```bash
docker compose logs -f worker
# Expect: job_claimed (type=transcribe) → job_succeeded → next job_claimed (type=extract)
```

### 8. Verify the database state

```bash
docker compose exec postgres psql -U fielddesk -d fielddesk -c \
  "SELECT id, voice_note_id, provider, model, duration_ms, left(text, 60) AS preview
   FROM transcripts ORDER BY created_at DESC LIMIT 3;"

docker compose exec postgres psql -U fielddesk -d fielddesk -c \
  "SELECT kind, provider, model, duration_ms, cost_usd, success
   FROM ai_model_calls ORDER BY created_at DESC LIMIT 3;"

docker compose exec postgres psql -U fielddesk -d fielddesk -c \
  "SELECT id, status FROM voice_notes ORDER BY created_at DESC LIMIT 3;"

docker compose exec postgres psql -U fielddesk -d fielddesk -c \
  "SELECT type, status, attempt_count FROM ai_jobs ORDER BY created_at DESC LIMIT 5;"
```

Expect:

- A `transcripts` row with `provider=stub`, `model=stub-transcriber-v1`.
- An `ai_model_calls` row with `kind=transcription`, `success=t`, `cost_usd=0`.
- The `voice_notes` row at `status=transcribed`.
- An `ai_jobs` row with `type=extract`, `status=succeeded` (extract is still a stub).

## Human review loop demo

Forces a review case, lists the queue, resolves with a correction, then
approves the resulting ticket. Tickets created down the happy extraction
path (high confidence) can be approved directly without going through the
review queue.

### 1. Force a review row by setting an unreachable confidence threshold

Edit `.env` (or pass via env), set `EXTRACTION_CONFIDENCE_THRESHOLD=0.99`,
then bring the stack up. With the stub extractor's confidence of `0.92`,
every extraction will route to a `human_reviews(reason=low_confidence)`
row.

```bash
sed -i.bak 's/^EXTRACTION_CONFIDENCE_THRESHOLD=.*/EXTRACTION_CONFIDENCE_THRESHOLD=0.99/' .env && rm -f .env.bak
docker compose up --build -d
docker compose restart worker
```

Run the upload + confirm flow from the earlier demo (steps 2 through 6
under "Vertical-slice demo"). When the worker processes the extract job,
expect a `human_reviews` row to appear with `status=open`, `reason=low_confidence`,
and FKs pointing back to the voice note / transcript / extraction.

### 2. List the review queue

```bash
TENANT_ID=$(./scripts/seed.sh)
curl -sS "http://localhost:8080/v1/review-queue?status=open&limit=20" \
  -H "X-Tenant-ID: $TENANT_ID" | python3 -m json.tool
```

You should see one or more items. Each item contains the `review`, plus
`voice_note`, `transcript` (with a `preview` of the first ~280 chars),
`extraction` (with `parsed_output` so the reviewer can pre-populate the
correction form), and `draft_ticket` (null when the AI didn't create one).

Filter by reason:

```bash
curl -sS "http://localhost:8080/v1/review-queue?reason=low_confidence" \
  -H "X-Tenant-ID: $TENANT_ID" | python3 -m json.tool
```

### 3. Resolve a review with a correction

```bash
REVIEW_ID=$(curl -sS "http://localhost:8080/v1/review-queue?status=open&limit=1" \
  -H "X-Tenant-ID: $TENANT_ID" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["items"][0]["review"]["id"])')

curl -sS -X POST "http://localhost:8080/v1/review-queue/$REVIEW_ID/resolve" \
  -H "Content-Type: application/json" -H "X-Tenant-ID: $TENANT_ID" \
  -d '{
    "correction": {
      "customer_name": "Jane Doe",
      "customer_phone": "555-0100",
      "service_address": "742 Evergreen Terrace",
      "trade_type": "plumbing",
      "issue_summary": "Leaking water heater in basement",
      "detailed_description": "Customer asks for a morning visit. 5-year warranty applies.",
      "priority": "high",
      "preferred_visit_time": "tomorrow morning",
      "required_skills": ["plumbing"],
      "suggested_parts": ["water heater drain valve"],
      "safety_concerns": ["standing water near electrical panel"],
      "warranty_mentioned": true,
      "follow_up_questions": ["confirm water heater make and model"]
    },
    "notes": "Verified customer name and address with dispatcher."
  }' | python3 -m json.tool
```

The response includes the updated `review` (status `resolved`, correction
JSON stored, `job_ticket_id` set) and the new/updated `ticket` (status
`draft`, source `ai_extraction`).

### 4. Confirm a job_ticket was created/updated

```bash
docker compose exec postgres psql -U fielddesk -d fielddesk -c \
  "SELECT id, status, source, trade_type, priority, customer_name, issue_summary, confidence
   FROM job_tickets ORDER BY created_at DESC LIMIT 3;"

docker compose exec postgres psql -U fielddesk -d fielddesk -c \
  "SELECT id, status, reason, resolved_at, job_ticket_id IS NOT NULL AS linked
   FROM human_reviews ORDER BY created_at DESC LIMIT 3;"
```

### 5. List tickets and fetch one

```bash
curl -sS "http://localhost:8080/v1/tickets?limit=20" \
  -H "X-Tenant-ID: $TENANT_ID" | python3 -m json.tool

TICKET_ID=$(curl -sS "http://localhost:8080/v1/tickets?status=draft&limit=1" \
  -H "X-Tenant-ID: $TENANT_ID" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["tickets"][0]["id"])')

curl -sS "http://localhost:8080/v1/tickets/$TICKET_ID" \
  -H "X-Tenant-ID: $TENANT_ID" | python3 -m json.tool
```

### 6. Approve or reject the ticket

Approval is a terminal transition for a draft ticket. To test rejection, use a
different draft ticket or run the reject command instead of approve.

```bash
curl -sS -X POST "http://localhost:8080/v1/tickets/$TICKET_ID/approve" \
  -H "X-Tenant-ID: $TENANT_ID" | python3 -m json.tool
# status: "approved", approved_at: now
```

To reject a draft/needs_review ticket:

```bash
REJECT_TICKET_ID=$(curl -sS "http://localhost:8080/v1/tickets?status=draft&limit=1" \
  -H "X-Tenant-ID: $TENANT_ID" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["tickets"][0]["id"])')

curl -sS -X POST "http://localhost:8080/v1/tickets/$REJECT_TICKET_ID/reject" \
  -H "Content-Type: application/json" -H "X-Tenant-ID: $TENANT_ID" \
  -d '{"reason": "duplicate of TKT-1234"}' | python3 -m json.tool
# status: "rejected", rejected_at: now, rejected_reason set
```

### 7. Inspect the correction-rate view

```bash
docker compose exec postgres psql -U fielddesk -d fielddesk -c \
  "SELECT * FROM v_human_review_metrics;"
```

Columns: `tenant_id`, `total_reviews`, `resolved_reviews`, `open_reviews`,
`low_confidence_reviews`, `invalid_json_reviews`, `provider_uncertainty_reviews`,
`missing_fields_reviews`, `reviews_with_corrections`.

## Cost & observability demo

After running the vertical-slice demo (so `ai_model_calls` has rows), call
the new admin endpoints. They accept optional `from` / `to` (RFC3339) query
parameters; defaults to the last 7 days. The window is capped at 366 days.

```bash
# Tenant-scoped cost rollup + per-kind + per-model.
curl -s -H "X-Tenant-ID: $TENANT_ID" \
  "http://localhost:8080/v1/admin/costs?from=2026-05-01T00:00:00Z&to=2026-06-01T00:00:00Z" | jq

# Job counters, success / failure / retry rate, latency p50/p95 per kind.
curl -s -H "X-Tenant-ID: $TENANT_ID" \
  "http://localhost:8080/v1/admin/metrics" | jq

# Failures feed (success = false), cursor-paginated by created_at.
curl -s -H "X-Tenant-ID: $TENANT_ID" \
  "http://localhost:8080/v1/admin/failures?limit=20" | jq

# Raw model-call log with filters.
curl -s -H "X-Tenant-ID: $TENANT_ID" \
  "http://localhost:8080/v1/model-logs?kind=transcription&success=success&limit=10" | jq
```

`/v1/admin/costs` separates `success_cost_usd` from `failed_cost_usd` —
failed calls still cost money and are surfaced, not hidden.
`/v1/admin/metrics.job_success_rate` and `job_failure_rate` are over
*terminal* jobs only (`succeeded + failed`) so in-flight jobs don't skew
the rate. Pagination on `/v1/admin/failures` and `/v1/model-logs` uses an
RFC3339Nano `cursor` (pass the previous response's `next_cursor`).

## Web dashboard demo (Phase 3b)

```bash
docker compose up -d        # if not already running
pnpm install                # once
pnpm web:dev                # http://localhost:3000
```

1. Open <http://localhost:3000/settings>, paste the tenant UUID from
   `./scripts/seed.sh`, click **Save**. It writes to `localStorage` under
   `fielddesk.tenant_id` and `lib/api.ts` attaches `X-Tenant-ID` on every
   subsequent request.
2. Run the vertical-slice demo (above) so `ai_model_calls` has rows.
3. Open `/costs`. Adjust the **From** / **To** datetime inputs and hit
   **Refresh**. The rollup separates `successful_cost` from
   `failed_cost` — if a provider call fails after charging, it lands in
   the failed bucket and stays visible.
4. Open `/ai-logs`. Filter by **Kind** (`transcription` / `llm` /
   `embedding` / `rerank`), by **Provider**, or by **Success**. Click
   **Load more** to page through `ai_model_calls` via cursor.
5. Open `/failures`. Same shape, locked to `success = false`. The card
   at the top sums failed cost across the loaded rows.

The dashboard page (`/dashboard`) consumes `/v1/admin/metrics` and
`/v1/admin/costs`.

## Tenant budgets demo (Phase 3 bullet 5)

Set a tight cap so the next provider call trips it:

```bash
curl -s -X PUT -H "X-Tenant-ID: $TENANT_ID" -H "Content-Type: application/json" \
  -d '{"daily_budget_usd": 0.01, "monthly_budget_usd": 1.0, "pause_on_exceeded": true}' \
  http://localhost:8080/v1/admin/budgets | jq

# Read back the view: limits + today's spend + month-to-date + over flags.
curl -s -H "X-Tenant-ID: $TENANT_ID" http://localhost:8080/v1/admin/budgets | jq
```

Then re-run the vertical-slice demo. After the first `ai_model_calls`
row pushes the tenant over `$0.01`, the *next* `transcribe` / `extract` /
`embed` / `rag` job pulled by the worker will:

1. Read `v_tenant_budget_usage` (single source of truth, same view the
   API admin endpoint reads).
2. See `daily_over = true` and `pause_on_exceeded = true`.
3. Update its `ai_jobs` row to `status = 'needs_review'` with
   `error_class = 'budget_exceeded'` and a detail like
   `budget_exceeded: daily $0.0156 >= $0.01`.
4. Insert a `human_reviews` row with `reason = 'budget_exceeded'`.
5. Skip `handle_job` entirely — no provider call, no spend.

The job lands in `/admin/failures` (unified feed) and in
`/review-queue`. Clear the cap (`PUT` with null limits) or raise it to
unblock the queue; existing `needs_review` jobs stay there until the
operator resolves them.

`draft_ticket` jobs are exempt (no provider call → no spend).
`max_cost_per_ticket` is accepted by the upsert but **not yet enforced**
— deferred with the JSONB-denormalization for "most expensive tickets."

The same flow is available from the web app: open `/settings`, set the
tenant ID, and the **Tenant AI budgets** card below shows today's spend
vs. the daily cap, MTD spend vs. the monthly cap (with a colored
progress bar that turns yellow at 80% and red when over), plus inputs
to edit the caps and a toggle for `pause_on_exceeded`. Saving calls
`PUT /v1/admin/budgets` and re-reads the view so the bars refresh
immediately.

## Development Workflow

- **Migrations**: add a new file `infra/migrations/NNNNN_name.sql` (zero-padded) with `-- +goose Up`/`-- +goose Down` markers. Apply in Docker via `docker compose run --rm migrate`, or against a local Postgres via `./scripts/migrate.sh up` (needs the `goose` CLI installed: `go install github.com/pressly/goose/v3/cmd/goose@latest`).
- **API queries**: add SQL to `apps/api/sql/queries/`, then run `sqlc generate` (config in `apps/api/sqlc.yaml`). Do not hand-edit generated files.
- **Worker handlers**: add a service module under `apps/worker/fielddesk_worker/<area>/` and wire it into `jobs/dispatch.py`.
- **Web pages**: add a route under `apps/web/app/<route>/page.tsx`. The sidebar nav lives in `apps/web/app/layout.tsx`.

## Project Goals

- Convert voice notes into structured job tickets with confidence + review.
- Make every AI step observable: cost, latency, tokens, error class.
- Treat retries, idempotency, and human review as first-class.
- Use evals to compare prompt versions, not vibes.
- Keep the stack small: Go + Python + Next.js + Postgres + MinIO.

## Build Phases

See `docs/PRD.md` § 19. In order:

1. Voice-to-ticket MVP — auth, upload, transcribe, extract, edit ticket.
2. Reliability — jobs, retries, attempts, failure states, idempotency.
3. Cost & observability — model logs, cost rollups, latency, failures dashboard.
4. RAG — documents, chunking, embeddings, vector search, ticket suggestions.
5. Evals — golden cases, extraction + RAG runners, prompt comparison.

## Further Reading

- [`docs/PRD.md`](docs/PRD.md) — product requirements.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system design.
- [`docs/AI_WORKFLOWS.md`](docs/AI_WORKFLOWS.md) — per-workflow behavior, retries, fallbacks.
- [`docs/EVALS.md`](docs/EVALS.md) — how we measure AI quality.
- [`docs/SPEC.md`](docs/SPEC.md) — endpoints, schema, jobs, logging.
- [`AGENTS.md`](AGENTS.md) — rules for AI coding agents working in this repo.
