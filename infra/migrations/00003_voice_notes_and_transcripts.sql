-- +goose Up
-- +goose StatementBegin
CREATE TABLE voice_notes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    uploaded_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    object_key      TEXT NOT NULL,
    mime_type       TEXT NOT NULL,
    duration_ms     INTEGER,
    size_bytes      BIGINT,
    status          TEXT NOT NULL DEFAULT 'uploaded'
                      CHECK (status IN ('uploaded', 'transcribing', 'transcribed', 'failed')),
    error_class     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX voice_notes_tenant_id_idx ON voice_notes(tenant_id);
CREATE INDEX voice_notes_status_idx ON voice_notes(status);

CREATE TABLE transcripts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    voice_note_id   UUID NOT NULL REFERENCES voice_notes(id) ON DELETE CASCADE,
    text            TEXT NOT NULL,
    language        TEXT,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    cost_usd        NUMERIC(12, 6) NOT NULL DEFAULT 0,
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX transcripts_voice_note_id_idx ON transcripts(voice_note_id);
CREATE INDEX transcripts_tenant_id_idx ON transcripts(tenant_id);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS transcripts;
DROP TABLE IF EXISTS voice_notes;
-- +goose StatementEnd
