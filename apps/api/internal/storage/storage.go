package storage

import (
	"context"
	"path"
	"strings"
	"time"

	"github.com/google/uuid"
)

type ObjectStore interface {
	PresignPut(ctx context.Context, key, contentType string, expires time.Duration) (string, error)
	Stat(ctx context.Context, key string) (ObjectInfo, error)
	Exists(ctx context.Context, key string) (bool, error)
}

type ObjectInfo struct {
	Exists      bool
	Size        int64
	ContentType string
}

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
	for _, r := range filename {
		if r == '/' || r == '\\' || r == 0 {
			return "audio"
		}
	}
	return filename
}
