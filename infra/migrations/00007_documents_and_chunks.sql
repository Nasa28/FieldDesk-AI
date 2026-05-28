-- +goose Up
-- +goose StatementBegin
CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    uploaded_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    source_type     TEXT NOT NULL DEFAULT 'upload'
                      CHECK (source_type IN ('upload', 'past_ticket', 'manual')),
    object_key      TEXT,
    mime_type       TEXT,
    size_bytes      BIGINT,
    status          TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX documents_tenant_id_idx ON documents(tenant_id);
CREATE INDEX documents_status_idx ON documents(status);

CREATE TABLE document_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    text            TEXT NOT NULL,
    token_count     INTEGER,
    embedding       vector(1536),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX document_chunks_tenant_id_idx ON document_chunks(tenant_id);
CREATE INDEX document_chunks_document_id_idx ON document_chunks(document_id);
CREATE INDEX document_chunks_embedding_idx
    ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS document_chunks;
DROP TABLE IF EXISTS documents;
-- +goose StatementEnd
