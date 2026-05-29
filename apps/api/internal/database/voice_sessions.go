package database

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type VoiceLiveSession struct {
	ID         uuid.UUID  `json:"id"`
	TenantID   uuid.UUID  `json:"tenant_id"`
	UserID     uuid.UUID  `json:"user_id"`
	TokenHash  string     `json:"-"`
	Mode       string     `json:"mode"`
	ExpiresAt  time.Time  `json:"expires_at"`
	ConsumedAt *time.Time `json:"consumed_at,omitempty"`
	CreatedAt  time.Time  `json:"created_at"`
	LastUsedAt *time.Time `json:"last_used_at,omitempty"`
}

type CreateVoiceLiveSessionParams struct {
	TenantID  uuid.UUID
	UserID    uuid.UUID
	TokenHash string
	Mode      string
	ExpiresAt time.Time
}

func CreateVoiceLiveSession(ctx context.Context, db *DB, p CreateVoiceLiveSessionParams) (VoiceLiveSession, error) {
	const q = `
		INSERT INTO voice_sessions (tenant_id, user_id, token_hash, mode, expires_at)
		VALUES ($1, $2, $3, $4, $5)
		RETURNING id, tenant_id, user_id, token_hash, mode, expires_at, consumed_at, created_at, last_used_at
	`
	var out VoiceLiveSession
	err := db.QueryRow(ctx, q, p.TenantID, p.UserID, p.TokenHash, p.Mode, p.ExpiresAt).Scan(
		&out.ID, &out.TenantID, &out.UserID, &out.TokenHash, &out.Mode,
		&out.ExpiresAt, &out.ConsumedAt, &out.CreatedAt, &out.LastUsedAt,
	)
	return out, err
}

func ConsumeVoiceLiveSession(ctx context.Context, db *DB, tokenHash string) (VoiceLiveSession, error) {
	const q = `
		UPDATE voice_sessions
		SET consumed_at = now(),
		    last_used_at = now()
		WHERE token_hash = $1
		  AND expires_at > now()
		  AND consumed_at IS NULL
		RETURNING id, tenant_id, user_id, token_hash, mode, expires_at, consumed_at, created_at, last_used_at
	`
	var out VoiceLiveSession
	err := db.QueryRow(ctx, q, tokenHash).Scan(
		&out.ID, &out.TenantID, &out.UserID, &out.TokenHash, &out.Mode,
		&out.ExpiresAt, &out.ConsumedAt, &out.CreatedAt, &out.LastUsedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return VoiceLiveSession{}, ErrNotFound
	}
	return out, err
}
