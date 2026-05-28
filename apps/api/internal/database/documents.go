package database

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type Document struct {
	ID         uuid.UUID       `json:"id"`
	TenantID   uuid.UUID       `json:"tenant_id"`
	UploadedBy *uuid.UUID      `json:"uploaded_by,omitempty"`
	Title      string          `json:"title"`
	SourceType string          `json:"source_type"`
	ObjectKey  *string         `json:"object_key,omitempty"`
	MimeType   *string         `json:"mime_type,omitempty"`
	SizeBytes  *int64          `json:"size_bytes,omitempty"`
	Status     string          `json:"status"`
	ParseError *string         `json:"parse_error,omitempty"`
	Metadata   json.RawMessage `json:"metadata,omitempty"`
	ChunkCount int             `json:"chunk_count"`
	CreatedAt  time.Time       `json:"created_at"`
	UpdatedAt  time.Time       `json:"updated_at"`
}

const documentColumns = `
	id, tenant_id, uploaded_by, title, source_type,
	object_key, mime_type, size_bytes, status, parse_error, metadata,
	created_at, updated_at
`

func scanDocument(row pgx.Row, d *Document) error {
	var meta []byte
	if err := row.Scan(
		&d.ID, &d.TenantID, &d.UploadedBy, &d.Title, &d.SourceType,
		&d.ObjectKey, &d.MimeType, &d.SizeBytes, &d.Status, &d.ParseError, &meta,
		&d.CreatedAt, &d.UpdatedAt,
	); err != nil {
		return err
	}
	d.Metadata = json.RawMessage(meta)
	return nil
}

type CreateDocumentParams struct {
	ID         uuid.UUID
	TenantID   uuid.UUID
	UploadedBy *uuid.UUID
	Title      string
	ObjectKey  string
	MimeType   string
	SizeBytes  *int64
	Metadata   map[string]any
}

func CreateDocument(ctx context.Context, db *DB, p CreateDocumentParams) (Document, error) {
	meta := []byte("{}")
	if p.Metadata != nil {
		b, err := json.Marshal(p.Metadata)
		if err != nil {
			return Document{}, err
		}
		meta = b
	}
	const q = `
		INSERT INTO documents
			(id, tenant_id, uploaded_by, title, source_type,
			 object_key, mime_type, size_bytes, status, metadata)
		VALUES ($1, $2, $3, $4, 'upload', $5, $6, $7, 'pending', $8)
		RETURNING ` + documentColumns
	var d Document
	err := scanDocument(
		db.QueryRow(ctx, q,
			p.ID, p.TenantID, p.UploadedBy, p.Title,
			p.ObjectKey, p.MimeType, p.SizeBytes, meta,
		),
		&d,
	)
	return d, err
}

func GetDocument(ctx context.Context, db *DB, id, tenantID uuid.UUID) (Document, error) {
	const q = `
		SELECT ` + documentColumns + `,
		       (SELECT COUNT(*) FROM document_chunks
		         WHERE document_id = documents.id AND tenant_id = documents.tenant_id) AS chunk_count
		FROM documents
		WHERE id = $1 AND tenant_id = $2
	`
	var d Document
	var meta []byte
	err := db.QueryRow(ctx, q, id, tenantID).Scan(
		&d.ID, &d.TenantID, &d.UploadedBy, &d.Title, &d.SourceType,
		&d.ObjectKey, &d.MimeType, &d.SizeBytes, &d.Status, &d.ParseError, &meta,
		&d.CreatedAt, &d.UpdatedAt, &d.ChunkCount,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return Document{}, ErrNotFound
	}
	if err != nil {
		return Document{}, err
	}
	d.Metadata = json.RawMessage(meta)
	return d, nil
}

func ListDocuments(ctx context.Context, db *DB, tenantID uuid.UUID, limit, offset int32) ([]Document, error) {
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	const q = `
		SELECT ` + documentColumns + `,
		       (SELECT COUNT(*) FROM document_chunks
		         WHERE document_id = documents.id AND tenant_id = documents.tenant_id) AS chunk_count
		FROM documents
		WHERE tenant_id = $1
		ORDER BY created_at DESC
		LIMIT $2 OFFSET $3
	`
	rows, err := db.Query(ctx, q, tenantID, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]Document, 0)
	for rows.Next() {
		var d Document
		var meta []byte
		if err := rows.Scan(
			&d.ID, &d.TenantID, &d.UploadedBy, &d.Title, &d.SourceType,
			&d.ObjectKey, &d.MimeType, &d.SizeBytes, &d.Status, &d.ParseError, &meta,
			&d.CreatedAt, &d.UpdatedAt, &d.ChunkCount,
		); err != nil {
			return nil, err
		}
		d.Metadata = json.RawMessage(meta)
		out = append(out, d)
	}
	return out, rows.Err()
}

func DeleteDocument(ctx context.Context, db *DB, id, tenantID uuid.UUID) error {
	const q = `DELETE FROM documents WHERE id = $1 AND tenant_id = $2`
	tag, err := db.Exec(ctx, q, id, tenantID)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

type ConfirmDocumentUploadedParams struct {
	ID             uuid.UUID
	TenantID       uuid.UUID
	JobPayload     []byte
	IdempotencyKey string
	MaxAttempts    int32
}

type ConfirmDocumentUploadedResult struct {
	Document Document
	Job      AIJob
}

// ConfirmDocumentUploaded validates the document is in 'pending', enqueues
// the embed job, and commits both writes atomically. Mirrors the voice-note
// confirm flow so the upload handshake is identical from the client's view.
func ConfirmDocumentUploaded(
	ctx context.Context,
	db *DB,
	p ConfirmDocumentUploadedParams,
) (ConfirmDocumentUploadedResult, error) {
	tx, err := db.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return ConfirmDocumentUploadedResult{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	const lockDoc = `
		SELECT ` + documentColumns + `
		FROM documents
		WHERE id = $1 AND tenant_id = $2
		FOR UPDATE
	`
	var d Document
	if err := scanDocument(tx.QueryRow(ctx, lockDoc, p.ID, p.TenantID), &d); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return ConfirmDocumentUploadedResult{}, ErrNotFound
		}
		return ConfirmDocumentUploadedResult{}, err
	}

	switch d.Status {
	case "pending":
		const touch = `UPDATE documents SET updated_at = now() WHERE id = $1 AND tenant_id = $2 RETURNING updated_at`
		if err := tx.QueryRow(ctx, touch, p.ID, p.TenantID).Scan(&d.UpdatedAt); err != nil {
			return ConfirmDocumentUploadedResult{}, err
		}
	case "processing", "ready":
		// Confirm is idempotent: a client retry mid-flight should not error.
	case "failed":
		return ConfirmDocumentUploadedResult{}, ErrInvalidState
	default:
		return ConfirmDocumentUploadedResult{}, ErrInvalidState
	}

	const enqueueJob = `
		INSERT INTO ai_jobs (tenant_id, type, payload, idempotency_key, max_attempts)
		VALUES ($1, 'embed', $2, $3, $4)
		ON CONFLICT (tenant_id, idempotency_key) DO UPDATE
			SET updated_at = now()
		RETURNING ` + aiJobColumns
	maxAttempts := p.MaxAttempts
	if maxAttempts == 0 {
		maxAttempts = 5
	}
	var j AIJob
	if err := scanAIJob(tx.QueryRow(ctx, enqueueJob,
		p.TenantID, p.JobPayload, p.IdempotencyKey, maxAttempts,
	), &j); err != nil {
		return ConfirmDocumentUploadedResult{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return ConfirmDocumentUploadedResult{}, err
	}
	return ConfirmDocumentUploadedResult{Document: d, Job: j}, nil
}
