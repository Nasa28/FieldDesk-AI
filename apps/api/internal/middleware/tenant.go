package middleware

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/google/uuid"
)

type ctxKey string

const tenantIDKey ctxKey = "tenant_id"
const userIDKey ctxKey = "user_id"

func RequireTenant(db *database.DB) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if token := bearerToken(r.Header.Get("Authorization")); token != "" {
				auth, err := database.GetAuthContextBySession(
					r.Context(), db, database.HashSessionToken(token),
				)
				if errors.Is(err, database.ErrNotFound) {
					writeError(w, http.StatusUnauthorized, "invalid_token", "session is invalid or expired")
					return
				}
				if err != nil {
					writeError(w, http.StatusInternalServerError, "auth_failed", "could not validate session")
					return
				}
				ctx := context.WithValue(r.Context(), tenantIDKey, auth.Tenant.ID)
				ctx = context.WithValue(ctx, userIDKey, auth.User.ID)
				next.ServeHTTP(w, r.WithContext(ctx))
				return
			}

			raw := r.Header.Get("X-Tenant-ID")
			if raw == "" {
				writeError(w, http.StatusUnauthorized, "missing_tenant", "X-Tenant-ID header or bearer token is required")
				return
			}
			id, err := uuid.Parse(raw)
			if err != nil {
				writeError(w, http.StatusBadRequest, "invalid_tenant", "X-Tenant-ID must be a UUID")
				return
			}
			ctx := context.WithValue(r.Context(), tenantIDKey, id)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

func TenantFromContext(ctx context.Context) (uuid.UUID, bool) {
	id, ok := ctx.Value(tenantIDKey).(uuid.UUID)
	return id, ok
}

func UserFromContext(ctx context.Context) (*uuid.UUID, bool) {
	id, ok := ctx.Value(userIDKey).(uuid.UUID)
	if !ok {
		return nil, false
	}
	return &id, true
}

func bearerToken(header string) string {
	const prefix = "Bearer "
	if !strings.HasPrefix(header, prefix) {
		return ""
	}
	return strings.TrimSpace(strings.TrimPrefix(header, prefix))
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"error":   code,
		"message": message,
	})
}
