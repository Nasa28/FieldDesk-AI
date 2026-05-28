-- +goose Up
-- +goose StatementBegin
ALTER TABLE job_tickets ADD COLUMN rejected_reason TEXT;
ALTER TABLE job_tickets ADD COLUMN rejected_at TIMESTAMPTZ;

ALTER TABLE human_reviews
    ADD COLUMN voice_note_id     UUID REFERENCES voice_notes(id) ON DELETE SET NULL;
ALTER TABLE human_reviews
    ADD COLUMN transcript_id     UUID REFERENCES transcripts(id) ON DELETE SET NULL;
ALTER TABLE human_reviews
    ADD COLUMN ai_extraction_id  UUID REFERENCES ai_extractions(id) ON DELETE SET NULL;

UPDATE human_reviews hr
SET
    voice_note_id = COALESCE(hr.voice_note_id, vn.id, t.voice_note_id, et.voice_note_id),
    transcript_id = COALESCE(hr.transcript_id, t.id, ae.transcript_id),
    ai_extraction_id = COALESCE(hr.ai_extraction_id, ae.id)
FROM ai_jobs aj
LEFT JOIN transcripts t
    ON t.id = NULLIF(aj.payload->>'transcript_id', '')::uuid
   AND t.tenant_id = aj.tenant_id
LEFT JOIN voice_notes vn
    ON vn.id = NULLIF(aj.payload->>'voice_note_id', '')::uuid
   AND vn.tenant_id = aj.tenant_id
LEFT JOIN ai_extractions ae
    ON ae.id = NULLIF(aj.result->>'extraction_id', '')::uuid
   AND ae.tenant_id = aj.tenant_id
LEFT JOIN transcripts et
    ON et.id = ae.transcript_id
   AND et.tenant_id = ae.tenant_id
WHERE hr.ai_job_id = aj.id
  AND hr.tenant_id = aj.tenant_id;

UPDATE human_reviews hr
SET
    voice_note_id = COALESCE(hr.voice_note_id, jt.voice_note_id),
    transcript_id = COALESCE(hr.transcript_id, jt.transcript_id)
FROM job_tickets jt
WHERE hr.job_ticket_id = jt.id
  AND hr.tenant_id = jt.tenant_id;

UPDATE human_reviews hr
SET voice_note_id = t.voice_note_id
FROM transcripts t
WHERE hr.voice_note_id IS NULL
  AND hr.transcript_id = t.id
  AND hr.tenant_id = t.tenant_id;

WITH latest_extractions AS (
    SELECT DISTINCT ON (tenant_id, transcript_id)
        id,
        tenant_id,
        transcript_id
    FROM ai_extractions
    ORDER BY tenant_id, transcript_id, created_at DESC
)
UPDATE human_reviews hr
SET ai_extraction_id = le.id
FROM latest_extractions le
WHERE hr.ai_extraction_id IS NULL
  AND hr.transcript_id = le.transcript_id
  AND hr.tenant_id = le.tenant_id;

CREATE INDEX human_reviews_voice_note_id_idx    ON human_reviews(voice_note_id);
CREATE INDEX human_reviews_transcript_id_idx    ON human_reviews(transcript_id);
CREATE INDEX human_reviews_ai_extraction_id_idx ON human_reviews(ai_extraction_id);

CREATE OR REPLACE VIEW v_human_review_metrics AS
SELECT
    tenant_id,
    COUNT(*)                                                AS total_reviews,
    COUNT(*) FILTER (WHERE status = 'resolved')             AS resolved_reviews,
    COUNT(*) FILTER (WHERE status = 'open')                 AS open_reviews,
    COUNT(*) FILTER (WHERE reason = 'low_confidence')       AS low_confidence_reviews,
    COUNT(*) FILTER (WHERE reason = 'invalid_json')         AS invalid_json_reviews,
    COUNT(*) FILTER (WHERE reason = 'provider_uncertainty') AS provider_uncertainty_reviews,
    COUNT(*) FILTER (WHERE reason = 'missing_fields')       AS missing_fields_reviews,
    COUNT(*) FILTER (WHERE correction IS NOT NULL)          AS reviews_with_corrections
FROM human_reviews
GROUP BY tenant_id;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP VIEW IF EXISTS v_human_review_metrics;

DROP INDEX IF EXISTS human_reviews_ai_extraction_id_idx;
DROP INDEX IF EXISTS human_reviews_transcript_id_idx;
DROP INDEX IF EXISTS human_reviews_voice_note_id_idx;

ALTER TABLE human_reviews DROP COLUMN ai_extraction_id;
ALTER TABLE human_reviews DROP COLUMN transcript_id;
ALTER TABLE human_reviews DROP COLUMN voice_note_id;

ALTER TABLE job_tickets DROP COLUMN rejected_at;
ALTER TABLE job_tickets DROP COLUMN rejected_reason;
-- +goose StatementEnd
