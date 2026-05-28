-- +goose Up
-- +goose StatementBegin

-- Phase 1.5 (denormalization, PRD §12): attribute every ai_model_calls row
-- to the ticket it ultimately belongs to, so "most expensive tickets,"
-- "avg cost per ticket," and max_cost_per_ticket enforcement become single-
-- table aggregations instead of a request_meta JSONB walk.
--
-- ticket_id is nullable on purpose:
--   * transcription calls land before any ticket exists; the extraction
--     worker back-stamps them when it creates the ticket.
--   * if extraction routes to needs_review (no ticket), the call costs
--     stay tenant-attributed but ticket-orphaned.
--   * ON DELETE SET NULL: deleting a ticket shouldn't lose the historical
--     spend record — the cost just becomes ticket-orphaned again.

ALTER TABLE ai_model_calls
    ADD COLUMN ticket_id UUID REFERENCES job_tickets(id) ON DELETE SET NULL;

-- Partial index so the aggregation hot path (top tickets by cost) is fast
-- without bloating the index with the long tail of NULL-ticket rows
-- (transcriptions yet to be back-stamped, embedding calls, evals, etc.).
CREATE INDEX ai_model_calls_tenant_ticket_idx
    ON ai_model_calls(tenant_id, ticket_id)
    WHERE ticket_id IS NOT NULL;

-- Best-effort backfill from request_meta breadcrumbs. Only set ticket_id
-- when we can prove the target ticket exists for the same tenant — never
-- cross a tenant boundary.

-- 1) Direct: recommendations + RAG flows already write ticket_id into
--    request_meta. The regex guard avoids casting non-UUID JSON values.
UPDATE ai_model_calls amc
SET ticket_id = (request_meta->>'ticket_id')::uuid
FROM job_tickets jt
WHERE amc.ticket_id IS NULL
  AND amc.request_meta ? 'ticket_id'
  AND amc.request_meta->>'ticket_id' ~ '^[0-9a-f-]{36}$'
  AND jt.id = (amc.request_meta->>'ticket_id')::uuid
  AND jt.tenant_id = amc.tenant_id;

-- 2) Indirect: extraction + transcription calls carry voice_note_id.
--    Resolve via job_tickets.voice_note_id.
UPDATE ai_model_calls amc
SET ticket_id = jt.id
FROM job_tickets jt
WHERE amc.ticket_id IS NULL
  AND amc.tenant_id = jt.tenant_id
  AND jt.voice_note_id IS NOT NULL
  AND amc.request_meta ? 'voice_note_id'
  AND amc.request_meta->>'voice_note_id' ~ '^[0-9a-f-]{36}$'
  AND jt.voice_note_id = (amc.request_meta->>'voice_note_id')::uuid;

-- 3) Indirect: extraction calls that only carry transcript_id (no
--    voice_note_id). Resolve via job_tickets.transcript_id.
UPDATE ai_model_calls amc
SET ticket_id = jt.id
FROM job_tickets jt
WHERE amc.ticket_id IS NULL
  AND amc.tenant_id = jt.tenant_id
  AND jt.transcript_id IS NOT NULL
  AND amc.request_meta ? 'transcript_id'
  AND amc.request_meta->>'transcript_id' ~ '^[0-9a-f-]{36}$'
  AND jt.transcript_id = (amc.request_meta->>'transcript_id')::uuid;

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin

DROP INDEX IF EXISTS ai_model_calls_tenant_ticket_idx;
ALTER TABLE ai_model_calls DROP COLUMN IF EXISTS ticket_id;

-- +goose StatementEnd
