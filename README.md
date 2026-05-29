# FieldDesk AI

FieldDesk AI is a production-style applied AI system for field-service teams. It turns technician voice notes into structured job tickets, enriches those tickets with company knowledge through RAG, routes uncertain output to human review, and tracks every model call for cost, latency, token usage, and failure analysis.

This project is built as a portfolio-grade AI engineering system: not a thin demo, but a small, realistic stack with clear service boundaries, tenant isolation, background jobs, evals, observability, and safety controls.

## What It Does

- Converts technician voice notes into structured field-service tickets.
- Transcribes audio and extracts ticket fields with schema-validated LLM output.
- Flags low-confidence, invalid, missing, or sensitive outputs for human review.
- Uploads company documents and retrieves relevant SOPs, warranty policies, parts catalogs, and safety procedures.
- Synthesizes ticket-specific recommendations with citations.
- Provides ad-hoc knowledge-base Q&A through grounded RAG.
- Tracks AI cost, latency, tokens, provider failures, retry rates, and job health.
- Enforces tenant-level AI budgets before paid provider calls.
- Runs golden-set evals for extraction, retrieval, recommendations, and prompt-version comparison.
- Includes an optional realtime voice assistant backed by Gemini Live.

## Architecture

FieldDesk AI is split into three services with Postgres as the source of truth.

```text
            Browser
               |
               v
        Next.js Web App
               |
               v
          Go HTTP API ---------------> MinIO / S3
               |
               v
        Postgres + pgvector
               ^
               |
        Python AI Worker ------------> AI providers
```

Service responsibilities:

- **Web**: dispatcher/admin UI for tickets, voice notes, documents, review queue, costs, failures, settings, and assistant workflows.
- **API**: auth, tenancy, validation, object-storage presigning, ticket operations, document operations, dashboard endpoints, and job enqueueing.
- **Worker**: transcription, extraction, embeddings, retrieval, reranking, synthesis, evals, retries, provider-call logging, and budget enforcement.
- **Postgres**: app state, job queue, attempts, model-call logs, eval runs, budgets, tickets, reviews, documents, chunks, and vector search.

The API does not call AI providers directly. All paid provider work is isolated in the worker so retries, cost accounting, provider failures, and prompt behavior are handled in one place.

## Tech Stack

| Area | Technology |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript |
| API | Go 1.23, chi, pgx |
| Worker | Python 3.11, Pydantic, psycopg, tenacity, structlog |
| Database | Postgres 16, pgvector/halfvec, HNSW indexes, SQL views |
| Storage | MinIO locally, S3-compatible object storage in production-style flows |
| AI | OpenAI Whisper, OpenAI chat/JSON extraction, OpenAI embeddings, optional Voyage/Cohere reranking, Gemini Live |
| Infrastructure | Docker Compose, Goose migrations, pnpm monorepo |
| Quality | Go tests, pytest, golden-set evals, repo quality gates |

## Core Workflows

### Voice To Ticket

1. A technician uploads or records a voice note.
2. The API creates a voice-note row and returns a presigned upload URL.
3. The worker transcribes the uploaded audio.
4. The worker extracts structured ticket fields from the transcript.
5. The system validates JSON, computes confidence, and creates a draft ticket or routes to review.
6. Dispatchers edit, approve, or reject the ticket.

### RAG And Recommendations

1. Admins upload knowledge-base documents.
2. The worker parses, chunks, embeds, and indexes the content.
3. Ticket drafts trigger tenant-scoped hybrid retrieval.
4. Retrieved chunks are shown as related documents.
5. A synthesis step produces possible diagnosis, suggested parts, safety checklist, follow-up questions, and citations.

### Human Review

AI output is never treated as final by default. The system routes work to review when extraction confidence is low, required fields are missing, JSON is invalid, provider uncertainty is reported, or a budget gate blocks paid work.

### Observability And Cost Control

Every provider call writes to `ai_model_calls` with provider, model, tokens, duration, cost, success/failure, error class, and metadata. Admin endpoints expose cost rollups, job metrics, failure feeds, model-call logs, and tenant budgets.

## AI Safety And Reliability

- Transcript and document content are wrapped as untrusted data before model calls.
- Structured extraction is validated against Pydantic schemas.
- Prompt versions are registered, hashed, and compared through evals.
- RAG synthesis drops hallucinated citations that do not match retrieved chunks.
- Zero-context recommendation and answer flows short-circuit without spending on an LLM call.
- Jobs use idempotency keys, `FOR UPDATE SKIP LOCKED`, leases, retry attempts, exponential backoff, and terminal states.
- Tenant isolation is enforced through tenant-scoped queries and checked by quality gates.
- Budget enforcement happens before provider calls, so blocked jobs do not create additional spend.

## Measured Results

Seeded RAG eval using OpenAI `text-embedding-3-small`, 12 golden cases, measured on 2026-05-28:

| Metric | Hybrid Search | Hybrid + Voyage `rerank-2.5-lite` |
| --- | ---: | ---: |
| `recall@1` | 0.917 | 1.000 |
| `recall@3` | 1.000 | 1.000 |
| `recall@5` | 1.000 | 1.000 |
| `MRR` | 0.958 | 1.000 |

The rerank pass fixed a known paraphrase case where the hybrid retriever ranked a parts-catalog chunk above the warranty-policy answer. Total rerank cost for the 12-case eval was about `$0.0006`.

## Repository Layout

```text
fielddesk-ai/
|-- apps/
|   |-- api/          # Go HTTP API
|   |-- worker/       # Python AI worker
|   `-- web/          # Next.js dashboard
|-- docs/             # Product, architecture, workflows, evals, and technical specs
|-- infra/
|   |-- docker/       # Service Dockerfiles
|   |-- migrations/   # Goose SQL migrations
|   `-- seed_corpus/  # Demo RAG corpus
|-- scripts/          # Seed, migrate, eval, and quality helper scripts
|-- docker-compose.yml
|-- package.json
`-- .env.example
```

## Local Setup

Prerequisites:

- Docker and Docker Compose
- Optional for host development: Go 1.23, Python 3.11+, Node 20+, pnpm

Start the full stack:

```bash
cp .env.example .env
docker compose up --build
```

The default `.env.example` uses stub providers where possible, so the stack can run without paid AI calls. Add provider keys when you want real transcription, extraction, embeddings, reranking, or live voice.

Service URLs:

| Service | URL |
| --- | --- |
| Web app | http://localhost:3000 |
| API | http://localhost:8080 |
| API health | http://localhost:8080/healthz |
| API readiness | http://localhost:8080/readyz |
| MinIO console | http://localhost:9001 |
| MinIO S3 API | http://localhost:9000 |
| Postgres | localhost:5432 |

Stop the stack:

```bash
docker compose down
```

Reset local state:

```bash
docker compose down -v
```

## Demo Data And Evals

Seed a demo tenant:

```bash
TENANT_ID=$(./scripts/seed.sh)
echo "$TENANT_ID"
```

Seed the knowledge-base corpus and wait for document ingestion:

```bash
./scripts/seed-corpus.sh "$TENANT_ID" http://localhost:8080 --wait
```

Run the eval suite:

```bash
./scripts/eval.sh "$TENANT_ID" all
```

Compare extraction prompt versions:

```bash
cd apps/worker
python -m fielddesk_worker.evals \
  --tenant "$TENANT_ID" \
  --kind extraction \
  --compare extract.v1.injection-hardened,extract.v2.ablation
```

## Development Commands

From the repo root:

```bash
pnpm web:typecheck
pnpm web:build
pnpm gates
```

API tests:

```bash
cd apps/api
go test ./...
```

Worker tests:

```bash
cd apps/worker
pytest
```

## Key Documentation

- [Product Requirements](docs/PRD.md)
- [Architecture](docs/ARCHITECTURE.md)
- [AI Workflows](docs/AI_WORKFLOWS.md)
- [Evals](docs/EVALS.md)
- [Technical Spec](docs/SPEC.md)

## Project Status

Implemented areas include voice-note upload, transcription, structured extraction, human review, ticket approval, document upload, parsing, embeddings, hybrid RAG, recommendation synthesis, knowledge-base Q&A, cost dashboards, failure dashboards, budget controls, evals, prompt-version comparison, and an optional Gemini Live voice assistant.

This repository remains an applied AI portfolio project, so implementation choices are intentionally explicit and measurable: AI outputs are validated, provider calls are auditable, retrieval quality is evaluated, and operational failure states are visible.
