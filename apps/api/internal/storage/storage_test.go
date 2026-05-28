package storage

import (
	"strings"
	"testing"

	"github.com/google/uuid"
)

func TestObjectKeyForVoiceNoteIncludesPersistedIDAndSanitizedFilename(t *testing.T) {
	tenantID := uuid.MustParse("11111111-1111-1111-1111-111111111111")
	voiceNoteID := uuid.MustParse("22222222-2222-2222-2222-222222222222")

	key := ObjectKeyForVoiceNote(tenantID, voiceNoteID, "../note.mp3")

	if !strings.Contains(key, tenantID.String()) {
		t.Fatalf("expected key to include tenant id, got %q", key)
	}
	if !strings.Contains(key, voiceNoteID.String()) {
		t.Fatalf("expected key to include voice note id, got %q", key)
	}
	if strings.Contains(key, "..") {
		t.Fatalf("expected key to sanitize path traversal, got %q", key)
	}
}
