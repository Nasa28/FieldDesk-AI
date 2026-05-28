-- +goose Up
-- +goose StatementBegin

-- Phase 4.5 — RAG synthesis. Retrieval alone returns chunks; this table holds
-- the structured recommendations the LLM synthesizes from those chunks
-- (suggested parts, safety checklist, possible diagnosis, follow-up
-- questions). Kept separate from job_tickets so:
--   1. We retain history across re-synthesis (e.g. after a ticket edit).
--   2. Cost / latency attribution lives on the row that incurred it, not on
--      the ticket schema.
--   3. The ticket page can show "synthesized from rag_query X" by joining.

CREATE TABLE ticket_recommendations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    job_ticket_id           UUID NOT NULL REFERENCES job_tickets(id) ON DELETE CASCADE,
    rag_query_id            UUID REFERENCES rag_queries(id) ON DELETE SET NULL,

    -- Structured synthesis output. Schema lives in
    -- apps/worker/fielddesk_worker/recommendations/schema.py
    -- (RecommendationsOutput pydantic model). Keys: possible_diagnosis,
    -- suggested_parts, safety_checklist, follow_up_questions, citations.
    output                  JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- AGENTS.md: low-confidence AI output goes to human review. Same idea
    -- here: we expose a self-reported confidence so a reviewer (or the UI)
    -- can dim the suggestion. Not a strict threshold yet — UI surfaces it.
    confidence              DOUBLE PRECISION,

    -- Provenance for the synthesis call itself. provider / model are repeated
    -- from ai_model_calls so the row is self-describing for the dashboard
    -- without a join; the canonical cost truth still lives in ai_model_calls.
    provider                TEXT NOT NULL,
    model                   TEXT NOT NULL,
    prompt_version          TEXT NOT NULL,
    schema_version          TEXT NOT NULL,

    input_tokens            INTEGER NOT NULL DEFAULT 0,
    output_tokens           INTEGER NOT NULL DEFAULT 0,
    cost_usd                NUMERIC(12, 6) NOT NULL DEFAULT 0,
    duration_ms             INTEGER NOT NULL DEFAULT 0,

    json_valid              BOOLEAN NOT NULL DEFAULT true,
    error_message           TEXT,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ticket_recommendations_tenant_id_idx
    ON ticket_recommendations(tenant_id);
CREATE INDEX ticket_recommendations_job_ticket_id_created_idx
    ON ticket_recommendations(job_ticket_id, created_at DESC);

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin

DROP TABLE IF EXISTS ticket_recommendations;

-- +goose StatementEnd
