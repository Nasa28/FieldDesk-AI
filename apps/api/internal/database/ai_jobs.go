package database

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

const aiJobColumns = `
	id, tenant_id, type, status, payload, result, error_class, error_message,
	idempotency_key, attempt_count, max_attempts, run_after,
	locked_by, lease_expires_at, started_at, finished_at, created_at, updated_at
`

func scanAIJob(row pgx.Row, j *AIJob) error {
	return row.Scan(
		&j.ID, &j.TenantID, &j.Type, &j.Status, &j.Payload, &j.Result,
		&j.ErrorClass, &j.ErrorMessage, &j.IdempotencyKey, &j.AttemptCount,
		&j.MaxAttempts, &j.RunAfter, &j.LockedBy, &j.LeaseExpiresAt,
		&j.StartedAt, &j.FinishedAt, &j.CreatedAt, &j.UpdatedAt,
	)
}

type EnqueueAIJobParams struct {
	TenantID       uuid.UUID
	Type           string
	Payload        []byte
	IdempotencyKey string
	MaxAttempts    int32
}

func EnqueueAIJob(ctx context.Context, db *DB, p EnqueueAIJobParams) (AIJob, error) {
	q := `
			INSERT INTO ai_jobs (tenant_id, type, payload, idempotency_key, max_attempts)
			VALUES ($1, $2, $3, $4, $5)
			ON CONFLICT (tenant_id, idempotency_key) DO UPDATE
				SET updated_at = now()
			RETURNING ` + aiJobColumns
	maxAttempts := p.MaxAttempts
	if maxAttempts == 0 {
		maxAttempts = 5
	}
	var j AIJob
	err := scanAIJob(db.QueryRow(ctx, q, p.TenantID, p.Type, p.Payload, p.IdempotencyKey, maxAttempts), &j)
	return j, err
}

type ListAIJobsParams struct {
	TenantID uuid.UUID
	Status   string
	Type     string
	Limit    int32
	Offset   int32
}

func ListAIJobs(ctx context.Context, db *DB, p ListAIJobsParams) ([]AIJob, error) {
	limit := p.Limit
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	q := `SELECT ` + aiJobColumns + `
		FROM ai_jobs
		WHERE tenant_id = $1
		  AND ($2::text = '' OR status = $2)
		  AND ($3::text = '' OR type = $3)
		ORDER BY created_at DESC
		LIMIT $4 OFFSET $5`
	rows, err := db.Query(ctx, q, p.TenantID, p.Status, p.Type, limit, p.Offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]AIJob, 0)
	for rows.Next() {
		var j AIJob
		if err := scanAIJob(rows, &j); err != nil {
			return nil, err
		}
		out = append(out, j)
	}
	return out, rows.Err()
}

func GetAIJob(ctx context.Context, db *DB, id, tenantID uuid.UUID) (AIJob, error) {
	q := `SELECT ` + aiJobColumns + ` FROM ai_jobs WHERE id = $1 AND tenant_id = $2`
	var j AIJob
	err := scanAIJob(db.QueryRow(ctx, q, id, tenantID), &j)
	if errors.Is(err, pgx.ErrNoRows) {
		return AIJob{}, ErrNotFound
	}
	return j, err
}

func ListAIJobAttempts(ctx context.Context, db *DB, jobID, tenantID uuid.UUID) ([]AIJobAttempt, error) {
	const q = `
		SELECT a.id, a.job_id, a.attempt_number, a.status, a.error_class,
		       a.error_message, a.duration_ms, a.started_at, a.finished_at
		FROM ai_job_attempts a
		JOIN ai_jobs j ON j.id = a.job_id
		WHERE a.job_id = $1 AND j.tenant_id = $2
		ORDER BY a.attempt_number ASC, a.started_at ASC
	`
	rows, err := db.Query(ctx, q, jobID, tenantID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]AIJobAttempt, 0)
	for rows.Next() {
		var a AIJobAttempt
		if err := rows.Scan(
			&a.ID, &a.JobID, &a.AttemptNumber, &a.Status, &a.ErrorClass,
			&a.ErrorMessage, &a.DurationMS, &a.StartedAt, &a.FinishedAt,
		); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

func RetryAIJob(ctx context.Context, db *DB, id, tenantID uuid.UUID, additionalAttempts int32) (AIJob, error) {
	current, err := GetAIJob(ctx, db, id, tenantID)
	if err != nil {
		return AIJob{}, err
	}
	if current.Status != "failed" && current.Status != "needs_review" {
		return AIJob{}, ErrInvalidState
	}
	if additionalAttempts <= 0 {
		additionalAttempts = 5
	}

	q := `UPDATE ai_jobs
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
			RETURNING ` + aiJobColumns
	var j AIJob
	err = scanAIJob(db.QueryRow(ctx, q, id, tenantID, additionalAttempts), &j)
	if errors.Is(err, pgx.ErrNoRows) {
		return AIJob{}, ErrInvalidState
	}
	return j, err
}
