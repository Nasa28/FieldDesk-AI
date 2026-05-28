-- name: GetTicket :one
SELECT *
FROM job_tickets
WHERE id = $1 AND tenant_id = $2;

-- name: ListTickets :many
SELECT *
FROM job_tickets
WHERE tenant_id = $1
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status'))
ORDER BY created_at DESC
LIMIT $2 OFFSET $3;

-- name: ApproveTicket :one
UPDATE job_tickets
SET status = 'approved',
    approved_at = now(),
    approved_by = $3,
    rejected_at = NULL,
    rejected_reason = NULL,
    updated_at = now()
WHERE id = $1 AND tenant_id = $2
RETURNING *;

-- name: RejectTicket :one
UPDATE job_tickets
SET status = 'rejected',
    rejected_at = now(),
    rejected_reason = NULLIF($3, ''),
    approved_at = NULL,
    approved_by = NULL,
    updated_at = now()
WHERE id = $1 AND tenant_id = $2
RETURNING *;
