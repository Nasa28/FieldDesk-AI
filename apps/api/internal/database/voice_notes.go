package database

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type CreateVoiceNoteParams struct {
	TenantID   uuid.UUID
	UploadedBy *uuid.UUID
	ObjectKey  string
	MimeType   string
	SizeBytes  *int64
	Status     string
}

func CreateVoiceNote(ctx context.Context, db *DB, p CreateVoiceNoteParams) (VoiceNote, error) {
	const q = `
		INSERT INTO voice_notes (tenant_id, uploaded_by, object_key, mime_type, size_bytes, status)
		VALUES ($1, $2, $3, $4, $5, $6)
		RETURNING id, tenant_id, uploaded_by, object_key, mime_type, duration_ms, size_bytes,
		          status, error_class, created_at, updated_at
	`
	var v VoiceNote
	err := db.QueryRow(ctx, q,
		p.TenantID, p.UploadedBy, p.ObjectKey, p.MimeType, p.SizeBytes, p.Status,
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

var ErrNotFound = errors.New("not found")
