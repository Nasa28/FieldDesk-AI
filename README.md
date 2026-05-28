# FieldDesk AI

A voice-to-ticket system for field service teams. Technicians upload voice notes;
FieldDesk transcribes them, extracts structured ticket fields, retrieves relevant
company knowledge via RAG, drafts a ticket, and routes uncertain output to human
review. Every model call is logged with cost, tokens, latency, and success.

This repo is built as an applied-AI portfolio project. The goal is not "a demo
that works"; it is "a system you would be unembarrassed to put in front of a
production team." See `docs/PRD.md` and `AGENTS.md` for the rules of the road.

## Status

**Phase 1, step 1 implemented.** A client can create a voice-note record,
get a presigned URL, upload audio bytes directly to MinIO, and the worker
will pick up the resulting `transcribe` job and record an attempt with a
*fake* transcription result. Real auth, real transcription, extraction, RAG,
review, and the web UI are still placeholders.

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

## Vertical-slice demo (Phase 1, step 1)

End-to-end: create a voice-note record → request a presigned URL → upload to
MinIO → worker picks up the transcribe job → job ends `succeeded` with a fake
transcript on `ai_jobs.result` and an entry in `ai_job_attempts`.

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
# Make sure you have some audio file at hand.
AUDIO=/path/to/note.mp3
SIZE=$(wc -c < "$AUDIO" | tr -d ' ')

CREATE=$(curl -sS -X POST http://localhost:8080/v1/voice-notes \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: $TENANT_ID" \
  -d "{\"filename\":\"$(basename "$AUDIO")\",\"mime_type\":\"audio/mpeg\",\"size_bytes\":$SIZE}")
echo "$CREATE"
VN_ID=$(echo "$CREATE" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
```

You should get HTTP 201 with a row whose status is `pending_upload`.

### 4. Request a presigned upload URL (enqueues the transcribe job)

```bash
PRESIGN=$(curl -sS -X POST "http://localhost:8080/v1/voice-notes/$VN_ID/upload-url" \
  -H "X-Tenant-ID: $TENANT_ID")
echo "$PRESIGN"
UPLOAD_URL=$(echo "$PRESIGN" | python3 -c 'import json,sys;print(json.load(sys.stdin)["upload_url"])')
```

The response includes `upload_url`, `object_key`, `expires_at`, and the
enqueued `job` (`type: transcribe`, `status: pending`).

### 5. Upload to MinIO with curl

```bash
curl -sS -X PUT "$UPLOAD_URL" \
  -H "Content-Type: audio/mpeg" \
  --data-binary "@$AUDIO" -o /dev/null -w "HTTP %{http_code}\n"
```

Expect `HTTP 200`. Verify in the MinIO console at <http://localhost:9001> —
the object should appear under `fielddesk/tenants/<tenant>/voice-notes/<id>/`.

### 6. Confirm the worker processed the job

The worker logs JSON lines per job. Tail them:

```bash
docker compose logs -f worker
# Expect: job_claimed → job_succeeded with type=transcribe.
```

Then check the database:

```bash
docker compose exec postgres psql -U fielddesk -d fielddesk -c \
  "SELECT type, status, attempt_count, result FROM ai_jobs ORDER BY created_at DESC LIMIT 3;"

docker compose exec postgres psql -U fielddesk -d fielddesk -c \
  "SELECT job_id, attempt_number, status, duration_ms FROM ai_job_attempts ORDER BY started_at DESC LIMIT 3;"
```

You should see the `transcribe` job at `status=succeeded` with a stub
transcript in the `result` column and a matching `ai_job_attempts` row.

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
