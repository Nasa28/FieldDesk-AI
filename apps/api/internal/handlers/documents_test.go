package handlers

import (
	"strings"
	"testing"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/storage"
)

func TestValidateUploadedDocumentAcceptsMatchingMetadata(t *testing.T) {
	size := int64(42)
	mimeType := "text/markdown"
	d := database.Document{
		MimeType:  &mimeType,
		SizeBytes: &size,
	}
	info := storage.ObjectInfo{
		Exists:      true,
		Size:        42,
		ContentType: "text/markdown; charset=utf-8",
	}

	if err := validateUploadedDocument(d, info); err != nil {
		t.Fatalf("expected matching metadata to validate: %v", err)
	}
}

func TestValidateUploadedDocumentRejectsSizeMismatch(t *testing.T) {
	size := int64(42)
	mimeType := "text/plain"
	d := database.Document{
		MimeType:  &mimeType,
		SizeBytes: &size,
	}
	info := storage.ObjectInfo{
		Exists:      true,
		Size:        41,
		ContentType: "text/plain",
	}

	err := validateUploadedDocument(d, info)
	if err == nil || !strings.Contains(err.Error(), "size") {
		t.Fatalf("expected size mismatch error, got %v", err)
	}
}

func TestValidateUploadedDocumentRejectsContentTypeMismatch(t *testing.T) {
	size := int64(42)
	mimeType := "application/pdf"
	d := database.Document{
		MimeType:  &mimeType,
		SizeBytes: &size,
	}
	info := storage.ObjectInfo{
		Exists:      true,
		Size:        42,
		ContentType: "text/plain",
	}

	err := validateUploadedDocument(d, info)
	if err == nil || !strings.Contains(err.Error(), "content type") {
		t.Fatalf("expected content type mismatch error, got %v", err)
	}
}
