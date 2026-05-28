-- +goose Up
-- +goose StatementBegin
CREATE TABLE job_tickets (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    voice_note_id           UUID REFERENCES voice_notes(id) ON DELETE SET NULL,
    transcript_id           UUID REFERENCES transcripts(id) ON DELETE SET NULL,

    status                  TEXT NOT NULL DEFAULT 'draft'
                              CHECK (status IN ('draft', 'needs_review', 'approved', 'rejected', 'archived')),

    customer_name           TEXT,
    customer_phone          TEXT,
    service_address         TEXT,
    trade_type              TEXT,
    issue_summary           TEXT,
    detailed_description    TEXT,
    priority                TEXT,
    preferred_visit_time    TEXT,
    required_skills         TEXT[] NOT NULL DEFAULT '{}',
    suggested_parts         TEXT[] NOT NULL DEFAULT '{}',
    safety_concerns         TEXT[] NOT NULL DEFAULT '{}',
    warranty_mention        BOOLEAN,
    follow_up_questions     TEXT[] NOT NULL DEFAULT '{}',

    confidence              NUMERIC(4, 3),
    human_review_required   BOOLEAN NOT NULL DEFAULT false,

    approved_by             UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_at             TIMESTAMPTZ,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX job_tickets_tenant_id_idx ON job_tickets(tenant_id);
CREATE INDEX job_tickets_status_idx ON job_tickets(status);
CREATE INDEX job_tickets_voice_note_id_idx ON job_tickets(voice_note_id);

CREATE TABLE ai_extractions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    transcript_id       UUID NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    job_ticket_id       UUID REFERENCES job_tickets(id) ON DELETE SET NULL,

    prompt_version      TEXT NOT NULL,
    schema_version      TEXT NOT NULL,
    raw_output          JSONB NOT NULL,
    parsed_output       JSONB,
    json_valid          BOOLEAN NOT NULL DEFAULT false,
    confidence          NUMERIC(4, 3),

    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    cost_usd            NUMERIC(12, 6) NOT NULL DEFAULT 0,
    duration_ms         INTEGER NOT NULL DEFAULT 0,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ai_extractions_transcript_id_idx ON ai_extractions(transcript_id);
CREATE INDEX ai_extractions_tenant_id_idx ON ai_extractions(tenant_id);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS ai_extractions;
DROP TABLE IF EXISTS job_tickets;
-- +goose StatementEnd
