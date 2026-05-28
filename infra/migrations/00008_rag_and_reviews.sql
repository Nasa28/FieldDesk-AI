-- +goose Up
-- +goose StatementBegin
CREATE TABLE rag_queries (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    job_ticket_id       UUID REFERENCES job_tickets(id) ON DELETE SET NULL,
    query_text          TEXT NOT NULL,
    top_k               INTEGER NOT NULL DEFAULT 5,
    results             JSONB NOT NULL DEFAULT '[]'::jsonb,
    embedding_model     TEXT,
    cost_usd            NUMERIC(12, 6) NOT NULL DEFAULT 0,
    duration_ms         INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX rag_queries_tenant_id_idx ON rag_queries(tenant_id);
CREATE INDEX rag_queries_job_ticket_id_idx ON rag_queries(job_ticket_id);

CREATE TABLE human_reviews (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    job_ticket_id       UUID REFERENCES job_tickets(id) ON DELETE CASCADE,
    ai_job_id           UUID REFERENCES ai_jobs(id) ON DELETE SET NULL,
    reason              TEXT NOT NULL
                          CHECK (reason IN ('low_confidence', 'invalid_json',
                                            'missing_fields', 'unclear_audio',
                                            'sensitive', 'fallback', 'other')),
    status              TEXT NOT NULL DEFAULT 'open'
                          CHECK (status IN ('open', 'resolved', 'rejected')),
    reviewer_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    correction          JSONB,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ
);

CREATE INDEX human_reviews_tenant_id_status_idx ON human_reviews(tenant_id, status);
CREATE INDEX human_reviews_job_ticket_id_idx ON human_reviews(job_ticket_id);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS human_reviews;
DROP TABLE IF EXISTS rag_queries;
-- +goose StatementEnd
