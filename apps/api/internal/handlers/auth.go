package handlers

import (
	"crypto/rand"
	"encoding/base64"
	"errors"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/fielddesk-ai/api/internal/database"

	"golang.org/x/crypto/bcrypt"
)

const sessionTTL = 7 * 24 * time.Hour

var slugCleanupRE = regexp.MustCompile(`[^a-z0-9]+`)

type signupRequest struct {
	TenantName string  `json:"tenant_name"`
	TenantSlug *string `json:"tenant_slug,omitempty"`
	Email      string  `json:"email"`
	Password   string  `json:"password"`
	FullName   *string `json:"full_name,omitempty"`
}

type loginRequest struct {
	TenantSlug string `json:"tenant_slug"`
	Email      string `json:"email"`
	Password   string `json:"password"`
}

type authResponse struct {
	Token     string          `json:"token"`
	ExpiresAt time.Time       `json:"expires_at"`
	Tenant    database.Tenant `json:"tenant"`
	User      database.User   `json:"user"`
}

func (h *Handlers) Signup(w http.ResponseWriter, r *http.Request) {
	var req signupRequest
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_body", err.Error())
		return
	}
	req.TenantName = strings.TrimSpace(req.TenantName)
	req.Email = normalizeEmail(req.Email)
	if req.FullName != nil {
		fullName := strings.TrimSpace(*req.FullName)
		req.FullName = &fullName
		if fullName == "" {
			req.FullName = nil
		}
	}
	tenantSlug := ""
	if req.TenantSlug != nil {
		tenantSlug = normalizeSlug(*req.TenantSlug)
	}
	if tenantSlug == "" {
		tenantSlug = normalizeSlug(req.TenantName)
	}
	if req.TenantName == "" || tenantSlug == "" {
		writeError(w, http.StatusBadRequest, "invalid_tenant", "tenant_name is required")
		return
	}
	if !validEmail(req.Email) {
		writeError(w, http.StatusBadRequest, "invalid_email", "email must be valid")
		return
	}
	if len(req.Password) < 8 {
		writeError(w, http.StatusBadRequest, "invalid_password", "password must be at least 8 characters")
		return
	}

	hash, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		h.logger.Error("password_hash_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "signup_failed", "could not create account")
		return
	}
	token, err := newSessionToken()
	if err != nil {
		h.logger.Error("session_token_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "signup_failed", "could not create session")
		return
	}
	expiresAt := time.Now().UTC().Add(sessionTTL)
	auth, err := database.CreateTenantAdminSession(r.Context(), h.db, database.CreateTenantAdminParams{
		TenantName:   req.TenantName,
		TenantSlug:   tenantSlug,
		Email:        req.Email,
		PasswordHash: string(hash),
		FullName:     req.FullName,
		TokenHash:    database.HashSessionToken(token),
		ExpiresAt:    expiresAt,
	})
	if errors.Is(err, database.ErrConflict) {
		writeError(w, http.StatusConflict, "already_exists", "tenant slug or user already exists")
		return
	}
	if err != nil {
		h.logger.Error("signup_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "signup_failed", "could not create account")
		return
	}
	writeJSON(w, http.StatusCreated, authResponse{
		Token: token, ExpiresAt: auth.Session.ExpiresAt, Tenant: auth.Tenant, User: auth.User,
	})
}

func (h *Handlers) Login(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_body", err.Error())
		return
	}
	tenantSlug := normalizeSlug(req.TenantSlug)
	email := normalizeEmail(req.Email)
	login, err := database.GetLoginUser(r.Context(), h.db, tenantSlug, email)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusUnauthorized, "invalid_credentials", "invalid tenant, email, or password")
		return
	}
	if err != nil {
		h.logger.Error("login_lookup_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "login_failed", "could not log in")
		return
	}
	if err := bcrypt.CompareHashAndPassword([]byte(login.PasswordHash), []byte(req.Password)); err != nil {
		writeError(w, http.StatusUnauthorized, "invalid_credentials", "invalid tenant, email, or password")
		return
	}
	token, err := newSessionToken()
	if err != nil {
		h.logger.Error("session_token_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "login_failed", "could not create session")
		return
	}
	expiresAt := time.Now().UTC().Add(sessionTTL)
	session, err := database.CreateSession(
		r.Context(), h.db, login.Tenant.ID, login.User.ID,
		database.HashSessionToken(token), expiresAt,
	)
	if err != nil {
		h.logger.Error("session_create_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "login_failed", "could not create session")
		return
	}
	writeJSON(w, http.StatusOK, authResponse{
		Token: token, ExpiresAt: session.ExpiresAt, Tenant: login.Tenant, User: login.User,
	})
}

func (h *Handlers) Logout(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r.Header.Get("Authorization"))
	if token != "" {
		if err := database.DeleteSession(r.Context(), h.db, database.HashSessionToken(token)); err != nil {
			h.logger.Error("logout_failed", "error", err)
			writeError(w, http.StatusInternalServerError, "logout_failed", "could not log out")
			return
		}
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handlers) Me(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r.Header.Get("Authorization"))
	if token == "" {
		writeError(w, http.StatusUnauthorized, "missing_token", "Authorization bearer token is required")
		return
	}
	auth, err := database.GetAuthContextBySession(r.Context(), h.db, database.HashSessionToken(token))
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusUnauthorized, "invalid_token", "session is invalid or expired")
		return
	}
	if err != nil {
		h.logger.Error("me_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "me_failed", "could not load session")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"tenant":     auth.Tenant,
		"user":       auth.User,
		"expires_at": auth.Session.ExpiresAt,
	})
}

func newSessionToken() (string, error) {
	var buf [32]byte
	if _, err := rand.Read(buf[:]); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buf[:]), nil
}

func normalizeEmail(email string) string {
	return strings.ToLower(strings.TrimSpace(email))
}

func validEmail(email string) bool {
	return strings.Contains(email, "@") && strings.Contains(email, ".")
}

func normalizeSlug(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	value = slugCleanupRE.ReplaceAllString(value, "-")
	value = strings.Trim(value, "-")
	if len(value) > 64 {
		value = strings.Trim(value[:64], "-")
	}
	return value
}

func bearerToken(header string) string {
	const prefix = "Bearer "
	if !strings.HasPrefix(header, prefix) {
		return ""
	}
	return strings.TrimSpace(strings.TrimPrefix(header, prefix))
}
