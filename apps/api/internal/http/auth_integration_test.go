package http

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	stdhttp "net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/fielddesk-ai/api/internal/config"
	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/storage"
)

type noopObjectStore struct{}

func (noopObjectStore) PresignPut(context.Context, string, string, time.Duration) (string, error) {
	return "", nil
}

func (noopObjectStore) Stat(context.Context, string) (storage.ObjectInfo, error) {
	return storage.ObjectInfo{}, nil
}

func (noopObjectStore) Exists(context.Context, string) (bool, error) {
	return false, nil
}

func TestAuthSignupMeAndProtectedRouteIntegration(t *testing.T) {
	dsn := os.Getenv("FIELDDESK_API_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("set FIELDDESK_API_TEST_DATABASE_URL to run DB-backed auth integration test")
	}

	ctx := context.Background()
	db, err := database.Connect(ctx, dsn)
	if err != nil {
		t.Fatalf("connect test database: %v", err)
	}
	defer db.Close()

	slug := "auth-it-" + time.Now().UTC().Format("20060102150405")
	cleanup := func() {
		_, _ = db.Exec(ctx, "DELETE FROM tenants WHERE slug = $1", slug)
	}
	cleanup()
	t.Cleanup(cleanup)

	router := NewRouter(
		&config.Config{AllowTenantHeaderAuth: false},
		db,
		slog.New(slog.NewTextHandler(io.Discard, nil)),
		noopObjectStore{},
	)

	signup := postJSON(t, router, "/v1/auth/signup", map[string]any{
		"tenant_name": "Auth Integration Test Co",
		"tenant_slug": slug,
		"email":       "admin@" + slug + ".local",
		"password":    "correct horse battery staple",
		"full_name":   "Auth Tester",
	}, "")
	if signup.Code != stdhttp.StatusCreated {
		t.Fatalf("signup status=%d body=%s", signup.Code, signup.Body.String())
	}

	var signupBody struct {
		Token  string `json:"token"`
		Tenant struct {
			ID   string `json:"id"`
			Slug string `json:"slug"`
		} `json:"tenant"`
		User struct {
			ID    string `json:"id"`
			Email string `json:"email"`
		} `json:"user"`
	}
	decodeBody(t, signup.Body.Bytes(), &signupBody)
	if signupBody.Token == "" {
		t.Fatal("signup response did not include a bearer token")
	}
	if signupBody.Tenant.Slug != slug {
		t.Fatalf("signup tenant slug=%q want %q", signupBody.Tenant.Slug, slug)
	}

	me := get(t, router, "/v1/auth/me", "Bearer "+signupBody.Token)
	if me.Code != stdhttp.StatusOK {
		t.Fatalf("me status=%d body=%s", me.Code, me.Body.String())
	}
	var meBody struct {
		Tenant struct {
			ID   string `json:"id"`
			Slug string `json:"slug"`
		} `json:"tenant"`
		User struct {
			ID    string `json:"id"`
			Email string `json:"email"`
		} `json:"user"`
	}
	decodeBody(t, me.Body.Bytes(), &meBody)
	if meBody.Tenant.ID != signupBody.Tenant.ID || meBody.User.ID != signupBody.User.ID {
		t.Fatalf("me returned wrong principal: got tenant=%s user=%s want tenant=%s user=%s",
			meBody.Tenant.ID, meBody.User.ID, signupBody.Tenant.ID, signupBody.User.ID)
	}

	protected := get(t, router, "/v1/tickets/", "Bearer "+signupBody.Token)
	if protected.Code != stdhttp.StatusOK {
		t.Fatalf("protected route status=%d body=%s", protected.Code, protected.Body.String())
	}

	headerOnly := httptest.NewRecorder()
	req := httptest.NewRequest(stdhttp.MethodGet, "/v1/tickets/", nil)
	req.Header.Set("X-Tenant-ID", signupBody.Tenant.ID)
	router.ServeHTTP(headerOnly, req)
	if headerOnly.Code != stdhttp.StatusUnauthorized {
		t.Fatalf("header-only protected route status=%d body=%s; want 401 with gate off",
			headerOnly.Code, headerOnly.Body.String())
	}
}

func postJSON(
	t *testing.T, handler stdhttp.Handler, path string, body any, authHeader string,
) *httptest.ResponseRecorder {
	t.Helper()
	payload, err := json.Marshal(body)
	if err != nil {
		t.Fatalf("marshal request body: %v", err)
	}
	req := httptest.NewRequest(stdhttp.MethodPost, path, bytes.NewReader(payload))
	req.Header.Set("Content-Type", "application/json")
	if authHeader != "" {
		req.Header.Set("Authorization", authHeader)
	}
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	return rr
}

func get(t *testing.T, handler stdhttp.Handler, path, authHeader string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(stdhttp.MethodGet, path, nil)
	if authHeader != "" {
		req.Header.Set("Authorization", authHeader)
	}
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	return rr
}

func decodeBody(t *testing.T, body []byte, dst any) {
	t.Helper()
	if err := json.Unmarshal(body, dst); err != nil {
		t.Fatalf("decode response body: %v (body=%s)", err, string(body))
	}
}
