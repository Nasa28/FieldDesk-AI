package handlers

import (
	"net/http"
	"time"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/middleware"
)

// voiceTokenTTL bounds how long the WebSocket handshake token is valid. It is
// a short-lived, single-purpose voice_sessions row, not a normal REST auth
// session, because it travels in the WS URL query string.
const voiceTokenTTL = 10 * time.Minute

// VoiceConfig reports whether the live voice feature is enabled, so the web
// app can show/hide the Voice Assistant page without a failed request.
func (h *Handlers) VoiceConfig(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"voice_enabled": h.cfg.VoiceEnabled})
}

// CreateVoiceSession mints a short-lived, one-time voice token and returns the
// relay WebSocket URL. The browser can't set an Authorization header on a
// WebSocket, so the token rides in the query string; the relay consumes it
// from voice_sessions and it is never accepted by REST auth.
func (h *Handlers) CreateVoiceSession(w http.ResponseWriter, r *http.Request) {
	if !h.cfg.VoiceEnabled {
		writeError(w, http.StatusNotFound, "feature_disabled", "voice assistant is not configured")
		return
	}
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	userID, ok := middleware.UserFromContext(r.Context())
	if !ok || userID == nil {
		// Voice requires a real logged-in user (the dev X-Tenant-ID path has
		// no user to own the short-lived session row).
		writeError(w, http.StatusUnauthorized, "login_required", "voice assistant requires a signed-in user")
		return
	}

	// mode selects the session behavior: "qa" (knowledge-base Q&A, default) or
	// "intake" (conversational ticket intake). Anything else falls back to qa.
	mode := "qa"
	if r.URL.Query().Get("mode") == "intake" {
		mode = "intake"
	}

	token, err := newSessionToken()
	if err != nil {
		h.logger.Error("voice_token_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "session_failed", "could not create voice session")
		return
	}
	expiresAt := time.Now().UTC().Add(voiceTokenTTL)
	if _, err := database.CreateVoiceLiveSession(r.Context(), h.db, database.CreateVoiceLiveSessionParams{
		TenantID:  tenantID,
		UserID:    *userID,
		TokenHash: database.HashSessionToken(token),
		Mode:      mode,
		ExpiresAt: expiresAt,
	}); err != nil {
		h.logger.Error("voice_session_create_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "session_failed", "could not create voice session")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"ws_url":        "/v1/voice/ws?token=" + token,
		"expires_at":    expiresAt,
		"voice_enabled": true,
		"mode":          mode,
	})
}
