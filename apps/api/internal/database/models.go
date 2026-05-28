package database

import (
	"time"

	"github.com/google/uuid"
)

// Models in this file mirror what sqlc would generate from
// apps/api/sql/queries/*.sql against the current migrations.
// When sqlc is added to CI, the corresponding generated code under
// internal/database/db/ will replace this hand-written layer.

type VoiceNote struct {
	ID         uuid.UUID  `json:"id"`
	TenantID   uuid.UUID  `json:"tenant_id"`
	UploadedBy *uuid.UUID `json:"uploaded_by,omitempty"`
	ObjectKey  string     `json:"object_key"`
	MimeType   string     `json:"mime_type"`
	DurationMS *int32     `json:"duration_ms,omitempty"`
	SizeBytes  *int64     `json:"size_bytes,omitempty"`
	Status     string     `json:"status"`
	ErrorClass *string    `json:"error_class,omitempty"`
	CreatedAt  time.Time  `json:"created_at"`
	UpdatedAt  time.Time  `json:"updated_at"`
}

type AIJob struct {
	ID              uuid.UUID  `json:"id"`
	TenantID        uuid.UUID  `json:"tenant_id"`
	Type            string     `json:"type"`
	Status          string     `json:"status"`
	Payload         []byte     `json:"payload"`
	Result          []byte     `json:"result,omitempty"`
	ErrorClass      *string    `json:"error_class,omitempty"`
	ErrorMessage    *string    `json:"error_message,omitempty"`
	IdempotencyKey  string     `json:"idempotency_key"`
	AttemptCount    int32      `json:"attempt_count"`
	MaxAttempts     int32      `json:"max_attempts"`
	RunAfter        time.Time  `json:"run_after"`
	StartedAt       *time.Time `json:"started_at,omitempty"`
	FinishedAt      *time.Time `json:"finished_at,omitempty"`
	CreatedAt       time.Time  `json:"created_at"`
	UpdatedAt       time.Time  `json:"updated_at"`
}
