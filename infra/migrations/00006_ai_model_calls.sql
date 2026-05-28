-- +goose Up
-- +goose StatementBegin
CREATE TABLE ai_model_calls (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    job_id              UUID REFERENCES ai_jobs(id) ON DELETE SET NULL,

    kind                TEXT NOT NULL
                          CHECK (kind IN ('transcription', 'llm', 'embedding', 'rerank')),
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,

    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    duration_ms         INTEGER NOT NULL DEFAULT 0,
    cost_usd            NUMERIC(12, 6) NOT NULL DEFAULT 0,

    success             BOOLEAN NOT NULL,
    error_class         TEXT,
    error_message       TEXT,

    request_meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ai_model_calls_tenant_id_created_at_idx ON ai_model_calls(tenant_id, created_at DESC);
CREATE INDEX ai_model_calls_job_id_idx ON ai_model_calls(job_id);
CREATE INDEX ai_model_calls_kind_idx ON ai_model_calls(kind);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS ai_model_calls;
-- +goose StatementEnd
