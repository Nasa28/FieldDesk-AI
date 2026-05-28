package middleware

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/google/uuid"
)

// fakeAuthLookup lets the middleware exercise both the happy and error
// branches of session resolution without dragging in a real Postgres. The
// real plumbing (HashSessionToken, DB row scan) is the database package's
// job; the middleware's job is to translate lookup outcomes into HTTP
// responses + ctx propagation, and that's what's under test here.
type fakeAuthLookup struct {
	wantTokenHash string
	auth          database.AuthContext
	err           error
	called        bool
	gotTokenHash  string
}

func (f *fakeAuthLookup) GetAuthContextBySession(
	_ context.Context, tokenHash string,
) (database.AuthContext, error) {
	f.called = true
	f.gotTokenHash = tokenHash
	if f.wantTokenHash != "" && tokenHash != f.wantTokenHash {
		return database.AuthContext{}, database.ErrNotFound
	}
	if f.err != nil {
		return database.AuthContext{}, f.err
	}
	return f.auth, nil
}

func TestRequireTenantBearerHappyPathPopulatesContext(t *testing.T) {
	tenantID := uuid.New()
	userID := uuid.New()
	token := "tk-valid"
	lookup := &fakeAuthLookup{
		wantTokenHash: database.HashSessionToken(token),
		auth: database.AuthContext{
			Tenant:  database.Tenant{ID: tenantID},
			User:    database.User{ID: userID},
			Session: database.AuthSession{ExpiresAt: time.Now().Add(time.Hour)},
		},
	}

	var gotTenant uuid.UUID
	var gotUser *uuid.UUID
	rr := runMiddleware(t, lookup, true, "Bearer "+token, "", func(r *http.Request) {
		gotTenant, _ = TenantFromContext(r.Context())
		gotUser, _ = UserFromContext(r.Context())
	})

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 on valid bearer, got %d: %s", rr.Code, rr.Body.String())
	}
	if gotTenant != tenantID {
		t.Fatalf("tenant id missing from context: got %s want %s", gotTenant, tenantID)
	}
	if gotUser == nil || *gotUser != userID {
		t.Fatalf("user id missing from context: got %v want %s", gotUser, userID)
	}
	if !lookup.called {
		t.Fatal("lookup was not called for a bearer-bearing request")
	}
}

func TestRequireTenantBearerInvalidTokenIs401(t *testing.T) {
	lookup := &fakeAuthLookup{err: database.ErrNotFound}
	rr := runMiddleware(t, lookup, true, "Bearer wrong", "", nil)
	assertErrorBody(t, rr, http.StatusUnauthorized, "invalid_token")
}

func TestRequireTenantBearerLookupErrorIs500(t *testing.T) {
	lookup := &fakeAuthLookup{err: errors.New("db is on fire")}
	rr := runMiddleware(t, lookup, true, "Bearer any", "", nil)
	assertErrorBody(t, rr, http.StatusInternalServerError, "auth_failed")
}

func TestRequireTenantTenantHeaderAllowedPopulatesTenantOnly(t *testing.T) {
	tenantID := uuid.New()
	lookup := &fakeAuthLookup{}

	var gotTenant uuid.UUID
	var gotUser *uuid.UUID
	var userOK bool
	rr := runMiddleware(t, lookup, true, "", tenantID.String(), func(r *http.Request) {
		gotTenant, _ = TenantFromContext(r.Context())
		gotUser, userOK = UserFromContext(r.Context())
	})

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 on X-Tenant-ID with gate on, got %d: %s", rr.Code, rr.Body.String())
	}
	if gotTenant != tenantID {
		t.Fatalf("tenant id missing from context: got %s want %s", gotTenant, tenantID)
	}
	if userOK || gotUser != nil {
		t.Fatalf("user id should NOT be set for header-only auth: got %v", gotUser)
	}
	if lookup.called {
		t.Fatal("lookup should not be called when no bearer is presented")
	}
}

// The regression this test guards: if someone re-introduces the old
// "X-Tenant-ID always works" behavior, a curl with the header but no
// bearer must still 401 in production-shaped configs.
func TestRequireTenantTenantHeaderRejectedWhenGateOff(t *testing.T) {
	tenantID := uuid.New()
	lookup := &fakeAuthLookup{}
	rr := runMiddleware(t, lookup, false, "", tenantID.String(), nil)
	assertErrorBody(t, rr, http.StatusUnauthorized, "missing_token")
	if lookup.called {
		t.Fatal("lookup should not run when gate is off and no bearer is present")
	}
}

func TestRequireTenantMissingBothIs401(t *testing.T) {
	rr := runMiddleware(t, &fakeAuthLookup{}, true, "", "", nil)
	assertErrorBody(t, rr, http.StatusUnauthorized, "missing_tenant")
}

func TestRequireTenantHeaderInvalidUUIDIs400(t *testing.T) {
	rr := runMiddleware(t, &fakeAuthLookup{}, true, "", "not-a-uuid", nil)
	assertErrorBody(t, rr, http.StatusBadRequest, "invalid_tenant")
}

func TestRequireTenantNonBearerAuthorizationHeaderFallsThroughToTenantHeader(t *testing.T) {
	// A leftover "Basic ..." or otherwise non-Bearer Authorization header
	// should not be treated as a bearer attempt; the middleware should fall
	// through to the X-Tenant-ID branch (or 401 if the gate is off).
	tenantID := uuid.New()
	lookup := &fakeAuthLookup{}
	rr := runMiddleware(t, lookup, true, "Basic abc123", tenantID.String(), nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected fall-through to tenant header to succeed, got %d", rr.Code)
	}
	if lookup.called {
		t.Fatal("lookup should not run for a non-Bearer Authorization header")
	}
}

// runMiddleware wires the middleware around a stub next-handler and
// records whether/how it was reached. `inspect`, if non-nil, runs inside
// the next-handler and can pull values from the request context.
func runMiddleware(
	t *testing.T,
	lookup AuthLookup,
	allowTenantHeader bool,
	authHeader, tenantHeader string,
	inspect func(*http.Request),
) *httptest.ResponseRecorder {
	t.Helper()
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if inspect != nil {
			inspect(r)
		}
		w.WriteHeader(http.StatusOK)
	})
	handler := RequireTenant(lookup, allowTenantHeader)(next)
	req := httptest.NewRequest(http.MethodGet, "/v1/anything", nil)
	if authHeader != "" {
		req.Header.Set("Authorization", authHeader)
	}
	if tenantHeader != "" {
		req.Header.Set("X-Tenant-ID", tenantHeader)
	}
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	return rr
}

func assertErrorBody(t *testing.T, rr *httptest.ResponseRecorder, wantStatus int, wantCode string) {
	t.Helper()
	if rr.Code != wantStatus {
		t.Fatalf("status: got %d want %d (body=%s)", rr.Code, wantStatus, rr.Body.String())
	}
	var body map[string]string
	if err := json.NewDecoder(strings.NewReader(rr.Body.String())).Decode(&body); err != nil {
		t.Fatalf("response body is not JSON: %v (body=%s)", err, rr.Body.String())
	}
	if body["error"] != wantCode {
		t.Fatalf("error code: got %q want %q", body["error"], wantCode)
	}
}
