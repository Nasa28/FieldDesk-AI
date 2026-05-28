package database

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type CreateVoiceNoteParams struct {
	ID         uuid.UUID
	TenantID   uuid.UUID
	UploadedBy *uuid.UUID
	ObjectKey  string
	MimeType   string
	SizeBytes  *int64
	Status     string
}

func CreateVoiceNote(ctx context.Context, db *DB, p CreateVoiceNoteParams) (VoiceNote, error) {
	const q = `
			INSERT INTO voice_notes (id, tenant_id, uploaded_by, object_key, mime_type, size_bytes, status)
			VALUES ($1, $2, $3, $4, $5, $6, $7)
			RETURNING id, tenant_id, uploaded_by, object_key, mime_type, duration_ms, size_bytes,
			          status, error_class, created_at, updated_at
		`
	var v VoiceNote
	err := db.QueryRow(ctx, q,
		p.ID, p.TenantID, p.UploadedBy, p.ObjectKey, p.MimeType, p.SizeBytes, p.Status,
	).Scan(
		&v.ID, &v.TenantID, &v.UploadedBy, &v.ObjectKey, &v.MimeType, &v.DurationMS,
		&v.SizeBytes, &v.Status, &v.ErrorClass, &v.CreatedAt, &v.UpdatedAt,
	)
	return v, err
}

func GetVoiceNote(ctx context.Context, db *DB, id, tenantID uuid.UUID) (VoiceNote, error) {
	const q = `
		SELECT id, tenant_id, uploaded_by, object_key, mime_type, duration_ms, size_bytes,
		       status, error_class, created_at, updated_at
		FROM voice_notes
		WHERE id = $1 AND tenant_id = $2
	`
	var v VoiceNote
	err := db.QueryRow(ctx, q, id, tenantID).Scan(
		&v.ID, &v.TenantID, &v.UploadedBy, &v.ObjectKey, &v.MimeType, &v.DurationMS,
		&v.SizeBytes, &v.Status, &v.ErrorClass, &v.CreatedAt, &v.UpdatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return VoiceNote{}, ErrNotFound
	}
	return v, err
}

func ListVoiceNotes(ctx context.Context, db *DB, tenantID uuid.UUID, limit int32) ([]VoiceNote, error) {
	const q = `
		SELECT id, tenant_id, uploaded_by, object_key, mime_type, duration_ms, size_bytes,
		       status, error_class, created_at, updated_at
		FROM voice_notes
		WHERE tenant_id = $1
		ORDER BY created_at DESC
		LIMIT $2
	`
	rows, err := db.Query(ctx, q, tenantID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]VoiceNote, 0)
	for rows.Next() {
		var v VoiceNote
		if err := rows.Scan(
			&v.ID, &v.TenantID, &v.UploadedBy, &v.ObjectKey, &v.MimeType, &v.DurationMS,
			&v.SizeBytes, &v.Status, &v.ErrorClass, &v.CreatedAt, &v.UpdatedAt,
		); err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

func UpdateVoiceNoteStatus(ctx context.Context, db *DB, id, tenantID uuid.UUID, status string) error {
	const q = `
			UPDATE voice_notes
			SET status = $1, updated_at = now()
		WHERE id = $2 AND tenant_id = $3
	`
	tag, err := db.Exec(ctx, q, status, id, tenantID)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

type ConfirmVoiceNoteUploadedParams struct {
	ID             uuid.UUID
	TenantID       uuid.UUID
	JobPayload     []byte
	IdempotencyKey string
	MaxAttempts    int32
}

type ConfirmVoiceNoteUploadedResult struct {
	VoiceNote VoiceNote
	Job       AIJob
}

func ConfirmVoiceNoteUploaded(
	ctx context.Context,
	db *DB,
	p ConfirmVoiceNoteUploadedParams,
) (ConfirmVoiceNoteUploadedResult, error) {
	tx, err := db.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return ConfirmVoiceNoteUploadedResult{}, err
	}
	defer func() {
		_ = tx.Rollback(ctx)
	}()

	const selectVoiceNote = `
		SELECT id, tenant_id, uploaded_by, object_key, mime_type, duration_ms, size_bytes,
		       status, error_class, created_at, updated_at
		FROM voice_notes
		WHERE id = $1 AND tenant_id = $2
		FOR UPDATE
	`
	var v VoiceNote
	err = tx.QueryRow(ctx, selectVoiceNote, p.ID, p.TenantID).Scan(
		&v.ID, &v.TenantID, &v.UploadedBy, &v.ObjectKey, &v.MimeType, &v.DurationMS,
		&v.SizeBytes, &v.Status, &v.ErrorClass, &v.CreatedAt, &v.UpdatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return ConfirmVoiceNoteUploadedResult{}, ErrNotFound
	}
	if err != nil {
		return ConfirmVoiceNoteUploadedResult{}, err
	}

	switch v.Status {
	case "pending_upload":
		const updateStatus = `
			UPDATE voice_notes
			SET status = 'uploaded', updated_at = now()
			WHERE id = $1 AND tenant_id = $2
			RETURNING status, updated_at
		`
		if err := tx.QueryRow(ctx, updateStatus, p.ID, p.TenantID).Scan(&v.Status, &v.UpdatedAt); err != nil {
			return ConfirmVoiceNoteUploadedResult{}, err
		}
	case "uploaded", "transcribing", "transcribed":
	case "failed":
		return ConfirmVoiceNoteUploadedResult{}, ErrInvalidState
	default:
		return ConfirmVoiceNoteUploadedResult{}, ErrInvalidState
	}

	const enqueueJob = `
		INSERT INTO ai_jobs (tenant_id, type, payload, idempotency_key, max_attempts)
		VALUES ($1, 'transcribe', $2, $3, $4)
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
	err = tx.QueryRow(ctx, enqueueJob,
		p.TenantID, p.JobPayload, p.IdempotencyKey, maxAttempts,
	).Scan(
		&j.ID, &j.TenantID, &j.Type, &j.Status, &j.Payload, &j.Result,
		&j.ErrorClass, &j.ErrorMessage, &j.IdempotencyKey, &j.AttemptCount, &j.MaxAttempts,
		&j.RunAfter, &j.StartedAt, &j.FinishedAt, &j.CreatedAt, &j.UpdatedAt,
	)
	if err != nil {
		return ConfirmVoiceNoteUploadedResult{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return ConfirmVoiceNoteUploadedResult{}, err
	}
	return ConfirmVoiceNoteUploadedResult{VoiceNote: v, Job: j}, nil
}

var ErrNotFound = errors.New("not found")
var ErrInvalidState = errors.New("invalid state")
