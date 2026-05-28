-- name: EnqueueAIJob :one
INSERT INTO ai_jobs (tenant_id, type, payload, idempotency_key, max_attempts)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (tenant_id, idempotency_key) DO UPDATE
    SET updated_at = now()
RETURNING *;

-- name: GetAIJob :one
SELECT * FROM ai_jobs
WHERE id = $1 AND tenant_id = $2;

-- name: ListAIJobsByVoiceNote :many
SELECT * FROM ai_jobs
WHERE tenant_id = $1
  AND payload ->> 'voice_note_id' = $2
ORDER BY created_at ASC;
