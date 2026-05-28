# AGENTS.md — Guidance for AI coding agents

This repo is a production-minded AI engineering portfolio. Treat it like a real
system, not a demo. The rules below override default instincts an agent might have.

## Before you write any code

1. Read `docs/PRD.md` and `docs/ARCHITECTURE.md`. They explain *what* the system is and *how* it's shaped.
2. Skim `docs/AI_WORKFLOWS.md` and `docs/EVALS.md` if your change touches any AI step.
3. Skim `docs/SPEC.md` for the endpoint and table inventory.
4. For non-trivial changes, propose scope first. Ask: "what is the smallest change that delivers value?"

## Hard rules

- **Every model call is logged.** A provider call without an `ai_model_calls` row is a bug, even on failure. Cost still counts even when calls fail.
- **AI output is never final.** Tickets stay `draft` or `needs_review` until a human approves them via the API.
- **Low-confidence output goes to human review.** Insert into `human_reviews` with a reason; do not silently downgrade thresholds to avoid the queue.
- **Tenant boundaries are sacred.** Every query filters by `tenant_id` at the outermost level. Vector search included. A cross-tenant join is a security bug, not a refactor.
- **Migrations are written with Goose.** Add a new file under `infra/migrations/` using the next zero-padded number and the `-- +goose Up / Down / StatementBegin / StatementEnd` markers. Never edit a migration that has been applied in any environment.
- **Do not edit generated sqlc files.** Anything under `apps/api/internal/database/db/` is generated from `sql/queries/`. Edit the query, regenerate.
- **Jobs must be observable, measurable, and retryable.** Each has an idempotency key, attempts are recorded in `ai_job_attempts`, retries use exponential backoff, exhausted jobs surface in the UI.

## Style and design defaults

- **Keep backend code simple and explicit.** Prefer one clear handler + service + query over clever abstractions. Don't introduce DI frameworks. Don't introduce an ORM.
- **Avoid LangChain unless there is a clear reason.** Use the provider SDKs directly with a small adapter (see `apps/worker/fielddesk_worker/providers/base.py`). Heavy frameworks hide the things this project is built to expose: cost, retries, prompts, schemas.
- **Prefer small provider interfaces over framework-heavy abstractions.** A `TranscriptionProvider`, `LLMProvider`, `EmbeddingProvider` Protocol is enough.
- **Match existing patterns.** Sidebar nav, page structure, handler shape, migration naming — copy what's already there before inventing.

## Things to push back on

- Requests to bypass review thresholds to "speed things up."
- Requests to skip cost logging in a "fast path."
- Requests to add a vector store other than pgvector without a stated reason MVP needs it.
- Requests to add Redis, Kafka, or another runtime dependency before the Postgres queue has been outgrown.
- Requests to add a generic "agents framework." We are building application-specific AI workflows, not an agent platform.

## When implementing a feature

- Start with a narrow vertical slice.
- Do not add unrelated features.
- Keep provider integrations behind interfaces.
- Every AI call must be logged.
- Every AI output must be validated before use.
- Low-confidence AI output must route to human review.
- Retryable jobs must remain idempotent.
- Tenant boundaries must be enforced on every query.
- Update README after each working slice.
- Run `gofmt`, `go vet`, `go build`, `python3 -m compileall`, and `docker compose config -q` before reporting completion.

## When you finish a change

- Tests if the change is testable.
- An eval case if the change touches extraction or RAG output.
- A doc update if you changed an endpoint, schema, or workflow.
- A short note in the PR on cost / latency impact if your change touches any provider call.

## Quality gates

There is no GitHub Actions CI today. The Lefthook hooks defined in [lefthook.yml](lefthook.yml) ARE the gates. Install once with `pnpm install` (runs `lefthook install` via the `prepare` script).

**Pre-commit** (staged files, fast):
- `scripts/check-secrets.sh` — blocks AWS / Anthropic / OpenAI / Stripe / GitHub / Slack / PEM patterns.
- `node scripts/check-file-size.cjs --staged` — soft/hard line-count caps per area (300/500 for handlers, 350/550 for database files, etc.). First line `// lint-file-size: <reason>` (or `# lint-file-size:` for Python/sh) is the escape hatch.
- `block-env-files` / `block-pem-files` glob rules.
- `gofmt -w` on staged `*.go` files.

**Pre-push** (project-wide):
- `node scripts/check-file-size.cjs --all`.
- `CHECK_SECRETS_SCOPE=all scripts/check-secrets.sh`.
- `scripts/check-go-boundaries.sh` — handlers and HTTP layer must not import `pgx` / `database/sql` / sqlc and must not call `.Query/.QueryRow/.Exec/.Begin/.BeginTx` outside `apps/api/internal/database/`.
- `scripts/check-tenant-filter.py` — every SQL `WHERE` clause in `apps/api/internal/database/*.go`, `apps/api/sql/queries/*.sql`, and `apps/worker/fielddesk_worker/db_queries/*.py` must mention `tenant_id`. Escape: `// lint-tenant-filter: <reason>` or `# lint-tenant-filter: <reason>` on the line before the query.
- `scripts/check-ai-model-call-logging.py` — any worker file that calls `provider.transcribe/extract_ticket/embed/complete_json` must also call `insert_model_call` or `log_model_call_isolated`. Escape: `# lint-ai-logging: <reason>` anywhere in the file.
- `make -C apps/api quality` (`fmt-check vet build test`).
- `python3 -m compileall -q apps/worker/fielddesk_worker`.
- `docker compose --env-file .env.example config -q`.

**Local one-shot run** of every gate: `pnpm gates`.

**Skipping**: `LEFTHOOK=0 git commit ...` or `LEFTHOOK=0 git push ...` bypasses the hooks. Use it only with an explanation in the PR description; the hooks exist because we don't have a CI safety net.

**When you add a new gate**: extend `lefthook.yml`, add the script under `scripts/`, document it in this section, and update `pnpm gates` so a one-shot run still covers everything.
