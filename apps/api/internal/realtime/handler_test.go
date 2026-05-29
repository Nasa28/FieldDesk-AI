package realtime

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/fielddesk-ai/api/internal/database"
)

type fakeAuth struct {
	session database.VoiceLiveSession
	err     error
}

func (f fakeAuth) ConsumeVoiceLiveSession(context.Context, string) (database.VoiceLiveSession, error) {
	return f.session, f.err
}

func TestServeHTTPMissingTokenIs404(t *testing.T) {
	h := newHandler(nil, fakeAuth{err: database.ErrNotFound}, nil, 5, nil)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/voice/ws", nil)
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Errorf("missing token: status = %d, want 404", rec.Code)
	}
}

func TestServeHTTPInvalidTokenIs404(t *testing.T) {
	h := newHandler(nil, fakeAuth{err: database.ErrNotFound}, nil, 5, nil)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/voice/ws?token=bogus", nil)
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Errorf("invalid token: status = %d, want 404", rec.Code)
	}
}

func TestGroundingBlocksModelOutputUntilToolResult(t *testing.T) {
	st := relayState{ground: &groundingState{}}
	var messages []ServerMessage
	write := func(msg ServerMessage) {
		messages = append(messages, msg)
	}

	if st.canForwardModelOutput(write) {
		t.Fatal("model output should be blocked before a tool result")
	}
	if len(messages) != 1 || messages[0].Code != "search_required" {
		t.Fatalf("blocked output message = %+v", messages)
	}
	if st.canForwardModelOutput(write) {
		t.Fatal("second blocked output should still be blocked")
	}
	if len(messages) != 1 {
		t.Fatalf("blocked notification should be emitted once, got %d", len(messages))
	}

	st.markGrounded()
	if !st.canForwardModelOutput(write) {
		t.Fatal("model output should pass after a tool result")
	}

	st.resetGrounding()
	if st.canForwardModelOutput(write) {
		t.Fatal("new user turn should require a fresh tool result")
	}
}
