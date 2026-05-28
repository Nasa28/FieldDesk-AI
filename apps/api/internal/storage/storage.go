package storage

import (
	"context"
	"path"
	"strings"
	"time"

	"github.com/google/uuid"
)

// ObjectStore is the minimal blob-storage surface the API needs.
// MinIO/S3/R2 all satisfy it; the implementation lives in minio.go.
type ObjectStore interface {
	PresignPut(ctx context.Context, key, contentType string, expires time.Duration) (string, error)
}

// ObjectKeyForVoiceNote builds the canonical S3 object key for a voice note.
// Path layout: tenants/<tenant_id>/voice-notes/<voice_note_id>/<safe-filename>
// The filename is included so a download has a sensible name and so the
// extension survives — but it is sanitized to remove anything path-like.
func ObjectKeyForVoiceNote(tenantID, voiceNoteID uuid.UUID, filename string) string {
	clean := sanitizeFilename(filename)
	return path.Join(
		"tenants",
		tenantID.String(),
		"voice-notes",
		voiceNoteID.String(),
		clean,
	)
}

func sanitizeFilename(filename string) string {
	filename = path.Base(filename)
	filename = strings.TrimSpace(filename)
	if filename == "" || filename == "." || filename == "/" {
		return "audio"
	}
	// Disallow anything still looking suspicious after Base() — be conservative.
	for _, r := range filename {
		if r == '/' || r == '\\' || r == 0 {
			return "audio"
		}
	}
	return filename
}
