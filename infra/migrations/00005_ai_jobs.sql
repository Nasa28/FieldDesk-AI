-- +goose Up
-- +goose StatementBegin
CREATE TABLE ai_jobs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    type                TEXT NOT NULL
                          CHECK (type IN ('transcribe', 'extract', 'embed', 'rag', 'draft_ticket')),
    status              TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'processing', 'succeeded',
                                            'failed', 'retrying', 'needs_review')),
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    result              JSONB,
    error_class         TEXT,
    error_message       TEXT,

    idempotency_key     TEXT NOT NULL,
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    max_attempts        INTEGER NOT NULL DEFAULT 5,
    run_after           TIMESTAMPTZ NOT NULL DEFAULT now(),

    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX ai_jobs_status_run_after_idx ON ai_jobs(status, run_after);
CREATE INDEX ai_jobs_tenant_id_idx ON ai_jobs(tenant_id);
CREATE INDEX ai_jobs_type_status_idx ON ai_jobs(type, status);

CREATE TABLE ai_job_attempts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES ai_jobs(id) ON DELETE CASCADE,
    attempt_number  INTEGER NOT NULL,
    status          TEXT NOT NULL
                      CHECK (status IN ('succeeded', 'failed', 'timeout')),
    error_class     TEXT,
    error_message   TEXT,
    duration_ms     INTEGER,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

CREATE INDEX ai_job_attempts_job_id_idx ON ai_job_attempts(job_id);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS ai_job_attempts;
DROP TABLE IF EXISTS ai_jobs;
-- +goose StatementEnd
