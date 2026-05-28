-- name: EnqueueAIJob :one
INSERT INTO ai_jobs (tenant_id, type, payload, idempotency_key, max_attempts)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (tenant_id, idempotency_key) DO UPDATE
    SET updated_at = now()
RETURNING *;

-- name: GetAIJob :one
SELECT * FROM ai_jobs
WHERE id = $1 AND tenant_id = $2;

-- name: ListAIJobs :many
SELECT * FROM ai_jobs
WHERE tenant_id = $1
  AND ($2::text = '' OR status = $2)
  AND ($3::text = '' OR type = $3)
ORDER BY created_at DESC
LIMIT $4 OFFSET $5;

-- name: ListAIJobsByVoiceNote :many
SELECT * FROM ai_jobs
WHERE tenant_id = $1
  AND payload ->> 'voice_note_id' = $2
ORDER BY created_at ASC;

-- name: ListAIJobAttempts :many
SELECT a.*
FROM ai_job_attempts a
JOIN ai_jobs j ON j.id = a.job_id
WHERE a.job_id = $1 AND j.tenant_id = $2
ORDER BY a.attempt_number ASC, a.started_at ASC;

-- name: RetryAIJob :one
UPDATE ai_jobs
SET status = 'pending',
    max_attempts = GREATEST(max_attempts, attempt_count + $3),
    run_after = now(),
    started_at = NULL,
    finished_at = NULL,
    result = NULL,
    error_class = NULL,
    error_message = NULL,
    locked_by = NULL,
    lease_expires_at = NULL,
    updated_at = now()
WHERE id = $1
  AND tenant_id = $2
  AND status IN ('failed', 'needs_review')
RETURNING *;
