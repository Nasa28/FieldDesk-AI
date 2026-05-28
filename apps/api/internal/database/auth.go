package database

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

var ErrConflict = errors.New("conflict")

func HashSessionToken(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

type LoginUser struct {
	Tenant       Tenant
	User         User
	PasswordHash string
}

type CreateTenantAdminParams struct {
	TenantName   string
	TenantSlug   string
	Email        string
	PasswordHash string
	FullName     *string
	TokenHash    string
	ExpiresAt    time.Time
}

func CreateTenantAdminSession(
	ctx context.Context, db *DB, p CreateTenantAdminParams,
) (AuthContext, error) {
	tx, err := db.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return AuthContext{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var tenant Tenant
	const insertTenant = `
		INSERT INTO tenants (name, slug)
		VALUES ($1, $2)
		RETURNING id, name, slug, created_at, updated_at
	`
	if err := tx.QueryRow(ctx, insertTenant, p.TenantName, p.TenantSlug).Scan(
		&tenant.ID, &tenant.Name, &tenant.Slug, &tenant.CreatedAt, &tenant.UpdatedAt,
	); err != nil {
		if isUniqueViolation(err) {
			return AuthContext{}, ErrConflict
		}
		return AuthContext{}, err
	}

	var user User
	const insertUser = `
		INSERT INTO users (tenant_id, email, password_hash, full_name, role)
		VALUES ($1, $2, $3, $4, 'admin')
		RETURNING id, tenant_id, email, full_name, role, created_at, updated_at
	`
	if err := tx.QueryRow(ctx, insertUser,
		tenant.ID, strings.ToLower(p.Email), p.PasswordHash, p.FullName,
	).Scan(
		&user.ID, &user.TenantID, &user.Email, &user.FullName, &user.Role,
		&user.CreatedAt, &user.UpdatedAt,
	); err != nil {
		if isUniqueViolation(err) {
			return AuthContext{}, ErrConflict
		}
		return AuthContext{}, err
	}

	session, err := createSessionTx(ctx, tx, tenant.ID, user.ID, p.TokenHash, p.ExpiresAt)
	if err != nil {
		return AuthContext{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return AuthContext{}, err
	}
	return AuthContext{Tenant: tenant, User: user, Session: session}, nil
}

func GetLoginUser(ctx context.Context, db *DB, tenantSlug, email string) (LoginUser, error) {
	const q = `
		SELECT
			t.id, t.name, t.slug, t.created_at, t.updated_at,
			u.id, u.tenant_id, u.email, u.password_hash, u.full_name, u.role, u.created_at, u.updated_at
		FROM users u
		JOIN tenants t ON t.id = u.tenant_id
		WHERE t.slug = $1 AND lower(u.email) = lower($2)
	`
	var out LoginUser
	err := db.QueryRow(ctx, q, tenantSlug, email).Scan(
		&out.Tenant.ID, &out.Tenant.Name, &out.Tenant.Slug,
		&out.Tenant.CreatedAt, &out.Tenant.UpdatedAt,
		&out.User.ID, &out.User.TenantID, &out.User.Email, &out.PasswordHash,
		&out.User.FullName, &out.User.Role, &out.User.CreatedAt, &out.User.UpdatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return LoginUser{}, ErrNotFound
	}
	return out, err
}

func CreateSession(
	ctx context.Context, db *DB, tenantID, userID uuid.UUID, tokenHash string, expiresAt time.Time,
) (AuthSession, error) {
	return createSessionTx(ctx, db, tenantID, userID, tokenHash, expiresAt)
}

func createSessionTx(
	ctx context.Context,
	q interface {
		QueryRow(context.Context, string, ...any) pgx.Row
	},
	tenantID, userID uuid.UUID,
	tokenHash string,
	expiresAt time.Time,
) (AuthSession, error) {
	const insertSession = `
		INSERT INTO user_sessions (token_hash, tenant_id, user_id, expires_at)
		VALUES ($1, $2, $3, $4)
		RETURNING token_hash, tenant_id, user_id, expires_at, created_at, last_used_at
	`
	var s AuthSession
	err := q.QueryRow(ctx, insertSession, tokenHash, tenantID, userID, expiresAt).Scan(
		&s.TokenHash, &s.TenantID, &s.UserID, &s.ExpiresAt, &s.CreatedAt, &s.LastUsedAt,
	)
	return s, err
}

func GetAuthContextBySession(ctx context.Context, db *DB, tokenHash string) (AuthContext, error) {
	const q = `
		UPDATE user_sessions s
		SET last_used_at = now()
		FROM users u
		JOIN tenants t ON t.id = u.tenant_id
		WHERE s.user_id = u.id
		  AND s.tenant_id = t.id
		  AND s.token_hash = $1
		  AND s.expires_at > now()
		RETURNING
			t.id, t.name, t.slug, t.created_at, t.updated_at,
			u.id, u.tenant_id, u.email, u.full_name, u.role, u.created_at, u.updated_at,
			s.token_hash, s.tenant_id, s.user_id, s.expires_at, s.created_at, s.last_used_at
	`
	var out AuthContext
	err := db.QueryRow(ctx, q, tokenHash).Scan(
		&out.Tenant.ID, &out.Tenant.Name, &out.Tenant.Slug,
		&out.Tenant.CreatedAt, &out.Tenant.UpdatedAt,
		&out.User.ID, &out.User.TenantID, &out.User.Email, &out.User.FullName,
		&out.User.Role, &out.User.CreatedAt, &out.User.UpdatedAt,
		&out.Session.TokenHash, &out.Session.TenantID, &out.Session.UserID,
		&out.Session.ExpiresAt, &out.Session.CreatedAt, &out.Session.LastUsedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return AuthContext{}, ErrNotFound
	}
	return out, err
}

func DeleteSession(ctx context.Context, db *DB, tokenHash string) error {
	_, err := db.Exec(ctx, "DELETE FROM user_sessions WHERE token_hash = $1", tokenHash)
	return err
}

func isUniqueViolation(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23505"
}
