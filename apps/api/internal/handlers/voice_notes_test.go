package handlers

import (
	"strings"
	"testing"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/storage"
)

func TestValidateUploadedObjectAcceptsMatchingMetadata(t *testing.T) {
	size := int64(42)
	v := database.VoiceNote{
		MimeType:  "audio/mpeg",
		SizeBytes: &size,
	}
	info := storage.ObjectInfo{
		Exists:      true,
		Size:        42,
		ContentType: "audio/mpeg; charset=binary",
	}

	if err := validateUploadedObject(v, info); err != nil {
		t.Fatalf("expected matching metadata to validate: %v", err)
	}
}

func TestValidateUploadedObjectRejectsSizeMismatch(t *testing.T) {
	size := int64(42)
	v := database.VoiceNote{
		MimeType:  "audio/mpeg",
		SizeBytes: &size,
	}
	info := storage.ObjectInfo{
		Exists:      true,
		Size:        41,
		ContentType: "audio/mpeg",
	}

	err := validateUploadedObject(v, info)
	if err == nil || !strings.Contains(err.Error(), "size") {
		t.Fatalf("expected size mismatch error, got %v", err)
	}
}

func TestValidateUploadedObjectRejectsContentTypeMismatch(t *testing.T) {
	size := int64(42)
	v := database.VoiceNote{
		MimeType:  "audio/mpeg",
		SizeBytes: &size,
	}
	info := storage.ObjectInfo{
		Exists:      true,
		Size:        42,
		ContentType: "audio/wav",
	}

	err := validateUploadedObject(v, info)
	if err == nil || !strings.Contains(err.Error(), "content type") {
		t.Fatalf("expected content type mismatch error, got %v", err)
	}
}
