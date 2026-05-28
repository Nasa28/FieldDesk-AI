# FieldDesk AI

A voice-to-ticket system for field service teams. Technicians upload voice notes;
FieldDesk transcribes them, extracts structured ticket fields, retrieves relevant
company knowledge via RAG, drafts a ticket, and routes uncertain output to human
review. Every model call is logged with cost, tokens, latency, and success.

This repo is built as an applied-AI portfolio project. The goal is not "a demo
that works"; it is "a system you would be unembarrassed to put in front of a
production team." See `docs/PRD.md` and `AGENTS.md` for the rules of the road.

## Status

**Phase 1, step 5 implemented.** The human review loop is now end-to-end.
`GET /v1/review-queue` returns open reviews enriched with the linked voice
note, transcript, AI extraction, and draft ticket (when any). `POST
/v1/review-queue/{id}/resolve` accepts a `correction` payload, creates or
updates a draft `job_tickets` row in the same transaction, and marks the
review `resolved`. `POST /v1/tickets/{id}/approve` and `.../reject` finalize
the ticket. The previous extraction routing (low confidence, invalid JSON,
provider uncertainty, missing fields) keeps producing `human_reviews` rows;
the new endpoints now consume them. A `v_human_review_metrics` SQL view
exposes basic correction-rate counters. RAG, document upload, real auth,
and the web UI remain placeholders.

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

The worker `POST`s the transcript text plus a fixed system prompt to
`https://api.openai.com/v1/chat/completions` with `response_format=json_object`
and `temperature=0`. The response is parsed and validated against
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

### 6. Approve the ticket

```bash
curl -sS -X POST "http://localhost:8080/v1/tickets/$TICKET_ID/approve" \
  -H "X-Tenant-ID: $TENANT_ID" | python3 -m json.tool
# status: "approved", approved_at: now
```

### 7. Reject a different ticket

```bash
curl -sS -X POST "http://localhost:8080/v1/tickets/$TICKET_ID/reject" \
  -H "Content-Type: application/json" -H "X-Tenant-ID: $TENANT_ID" \
  -d '{"reason": "duplicate of TKT-1234"}' | python3 -m json.tool
# status: "rejected", rejected_at: now, rejected_reason set
```

### 8. Inspect the correction-rate view

```bash
docker compose exec postgres psql -U fielddesk -d fielddesk -c \
  "SELECT * FROM v_human_review_metrics;"
```

Columns: `tenant_id`, `total_reviews`, `resolved_reviews`, `open_reviews`,
`low_confidence_reviews`, `invalid_json_reviews`, `provider_uncertainty_reviews`,
`missing_fields_reviews`, `reviews_with_corrections`.

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
