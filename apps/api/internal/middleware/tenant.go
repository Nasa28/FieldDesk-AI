package middleware

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/google/uuid"
)

type ctxKey string

const tenantIDKey ctxKey = "tenant_id"

// Dev shortcut: real auth (sessions / JWT) will derive tenant_id from the
// authenticated principal instead of reading a header.
func RequireTenant(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw := r.Header.Get("X-Tenant-ID")
		if raw == "" {
			writeError(w, http.StatusUnauthorized, "missing_tenant", "X-Tenant-ID header is required")
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

func TenantFromContext(ctx context.Context) (uuid.UUID, bool) {
	id, ok := ctx.Value(tenantIDKey).(uuid.UUID)
	return id, ok
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"error":   code,
		"message": message,
	})
}
