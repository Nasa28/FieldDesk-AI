-- name: GetHumanReview :one
SELECT *
FROM human_reviews
WHERE id = $1 AND tenant_id = $2;

-- name: ListHumanReviews :many
SELECT
    hr.*,
    vn.status      AS voice_note_status,
    vn.mime_type   AS voice_note_mime_type,
    vn.created_at  AS voice_note_created_at,
    t.language     AS transcript_language,
    LEFT(COALESCE(t.text, ''), 280) AS transcript_preview,
    e.json_valid   AS extraction_json_valid,
    e.confidence   AS extraction_confidence,
    e.parsed_output AS extraction_parsed_output,
    e.error_message AS extraction_error_message,
    e.provider     AS extraction_provider,
    e.model        AS extraction_model,
    tk.status      AS ticket_status,
    tk.source      AS ticket_source,
    tk.customer_name AS ticket_customer_name,
    tk.issue_summary AS ticket_issue_summary
FROM human_reviews hr
LEFT JOIN voice_notes    vn ON vn.id = hr.voice_note_id    AND vn.tenant_id = hr.tenant_id
LEFT JOIN transcripts    t  ON t.id  = hr.transcript_id    AND t.tenant_id  = hr.tenant_id
LEFT JOIN ai_extractions e  ON e.id  = hr.ai_extraction_id AND e.tenant_id  = hr.tenant_id
LEFT JOIN job_tickets    tk ON tk.id = hr.job_ticket_id    AND tk.tenant_id = hr.tenant_id
WHERE hr.tenant_id = $1
  AND hr.status = $2
  AND (sqlc.narg('reason')::text IS NULL OR hr.reason = sqlc.narg('reason'))
ORDER BY hr.created_at DESC
LIMIT $3 OFFSET $4;

-- name: LockHumanReview :one
SELECT *
FROM human_reviews
WHERE id = $1 AND tenant_id = $2
FOR UPDATE;

-- name: MarkHumanReviewResolved :one
UPDATE human_reviews
SET status = 'resolved',
    resolved_at = now(),
    job_ticket_id = $3,
    correction = $4,
    notes = COALESCE($5, notes),
    reviewer_id = COALESCE($6, reviewer_id)
WHERE id = $1 AND tenant_id = $2
RETURNING *;
