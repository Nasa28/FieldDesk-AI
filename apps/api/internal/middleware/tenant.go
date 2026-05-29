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
const userRoleKey ctxKey = "user_role"

// AuthLookup resolves a hashed session token to the owning tenant + user.
// Production wires this to database.GetAuthContextBySession; tests pass a
// fake so the middleware can be exercised without a real Postgres.
type AuthLookup interface {
	GetAuthContextBySession(ctx context.Context, tokenHash string) (database.AuthContext, error)
}

// DatabaseAuthLookup adapts *database.DB to the AuthLookup interface. Kept
// trivial on purpose; the interface is what matters, not this adapter.
type DatabaseAuthLookup struct{ DB *database.DB }

func (d DatabaseAuthLookup) GetAuthContextBySession(
	ctx context.Context, tokenHash string,
) (database.AuthContext, error) {
	return database.GetAuthContextBySession(ctx, d.DB, tokenHash)
}

// RequireTenant enforces that every protected request carries either a
// bearer session token or, when allowTenantHeader is true, an X-Tenant-ID
// header. The env-gated header path exists so seed scripts and curl keep
// working in local dev without a login flow; production-style configs
// leave it off so a misconfigured deploy can't silently accept any caller
// who sets the header.
func RequireTenant(lookup AuthLookup, allowTenantHeader bool) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if token := bearerToken(r.Header.Get("Authorization")); token != "" {
				authenticateBearer(w, r, next, lookup, token)
				return
			}
			if !allowTenantHeader {
				writeError(w, http.StatusUnauthorized, "missing_token", "Authorization bearer token is required")
				return
			}
			authenticateTenantHeader(w, r, next)
		})
	}
}

func authenticateBearer(
	w http.ResponseWriter, r *http.Request, next http.Handler,
	lookup AuthLookup, token string,
) {
	auth, err := lookup.GetAuthContextBySession(r.Context(), database.HashSessionToken(token))
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
	ctx = context.WithValue(ctx, userRoleKey, auth.User.Role)
	next.ServeHTTP(w, r.WithContext(ctx))
}

func authenticateTenantHeader(w http.ResponseWriter, r *http.Request, next http.Handler) {
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

func UserRoleFromContext(ctx context.Context) (string, bool) {
	role, ok := ctx.Value(userRoleKey).(string)
	return role, ok
}

func RequireRole(allowed ...string) func(http.Handler) http.Handler {
	allowedSet := make(map[string]struct{}, len(allowed))
	for _, role := range allowed {
		allowedSet[role] = struct{}{}
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			role, ok := UserRoleFromContext(r.Context())
			if !ok {
				writeError(w, http.StatusForbidden, "missing_role", "user role is required")
				return
			}
			if _, ok := allowedSet[role]; !ok {
				writeError(w, http.StatusForbidden, "forbidden", "user role cannot access this resource")
				return
			}
			next.ServeHTTP(w, r)
		})
	}
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
