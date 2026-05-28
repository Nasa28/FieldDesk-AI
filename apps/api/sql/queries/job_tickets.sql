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
  AND status = 'draft'
RETURNING *;

-- name: UpdateTicket :one
UPDATE job_tickets
SET customer_name = COALESCE(sqlc.narg('customer_name'), customer_name),
    customer_phone = COALESCE(sqlc.narg('customer_phone'), customer_phone),
    service_address = COALESCE(sqlc.narg('service_address'), service_address),
    trade_type = COALESCE(sqlc.narg('trade_type'), trade_type),
    issue_summary = COALESCE(sqlc.narg('issue_summary'), issue_summary),
    detailed_description = COALESCE(sqlc.narg('detailed_description'), detailed_description),
    priority = COALESCE(sqlc.narg('priority'), priority),
    preferred_visit_time = COALESCE(sqlc.narg('preferred_visit_time'), preferred_visit_time),
    required_skills = COALESCE(sqlc.narg('required_skills')::text[], required_skills),
    suggested_parts = COALESCE(sqlc.narg('suggested_parts')::text[], suggested_parts),
    safety_concerns = COALESCE(sqlc.narg('safety_concerns')::text[], safety_concerns),
    warranty_mention = COALESCE(sqlc.narg('warranty_mention'), warranty_mention),
    follow_up_questions = COALESCE(sqlc.narg('follow_up_questions')::text[], follow_up_questions),
    status = 'draft',
    human_review_required = false,
    approved_at = NULL,
    approved_by = NULL,
    rejected_at = NULL,
    rejected_reason = NULL,
    updated_at = now()
WHERE id = $1 AND tenant_id = $2
  AND status IN ('draft', 'needs_review', 'rejected')
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
  AND status IN ('draft', 'needs_review')
RETURNING *;
