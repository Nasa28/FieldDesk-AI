package database

import (
	"context"

	"github.com/google/uuid"
)

type EnqueueAIJobParams struct {
	TenantID       uuid.UUID
	Type           string
	Payload        []byte
	IdempotencyKey string
	MaxAttempts    int32
}

// EnqueueAIJob inserts a new job row. If a row with the same
// (tenant_id, idempotency_key) already exists, the existing row is returned
// so the caller cannot accidentally create duplicate work.
func EnqueueAIJob(ctx context.Context, db *DB, p EnqueueAIJobParams) (AIJob, error) {
	const q = `
		INSERT INTO ai_jobs (tenant_id, type, payload, idempotency_key, max_attempts)
		VALUES ($1, $2, $3, $4, $5)
		ON CONFLICT (tenant_id, idempotency_key) DO UPDATE
			SET updated_at = now()
		RETURNING id, tenant_id, type, status, payload, result, error_class, error_message,
		          idempotency_key, attempt_count, max_attempts, run_after,
		          started_at, finished_at, created_at, updated_at
	`
	maxAttempts := p.MaxAttempts
	if maxAttempts == 0 {
		maxAttempts = 5
	}
	var j AIJob
	err := db.QueryRow(ctx, q, p.TenantID, p.Type, p.Payload, p.IdempotencyKey, maxAttempts).Scan(
		&j.ID, &j.TenantID, &j.Type, &j.Status, &j.Payload, &j.Result,
		&j.ErrorClass, &j.ErrorMessage, &j.IdempotencyKey, &j.AttemptCount, &j.MaxAttempts,
		&j.RunAfter, &j.StartedAt, &j.FinishedAt, &j.CreatedAt, &j.UpdatedAt,
	)
	return j, err
}
