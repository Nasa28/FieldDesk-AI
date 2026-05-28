package handlers

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/middleware"
	"github.com/fielddesk-ai/api/internal/storage"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

// allowedDocumentMimes is kept in sync with the worker parser registry
// (apps/worker/fielddesk_worker/parsing/base.py:SUPPORTED_MIME_TYPES). When
// extending, update both — there's no shared schema enforcing it.
var allowedDocumentMimes = map[string]struct{}{
	"text/plain":      {},
	"text/markdown":   {},
	"text/x-markdown": {},
	"application/pdf": {},
	"application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}, // .docx
}

type createDocumentRequest struct {
	Title     string `json:"title"`
	Filename  string `json:"filename"`
	MimeType  string `json:"mime_type"`
	SizeBytes int64  `json:"size_bytes"`
}

func (h *Handlers) CreateDocument(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}

	var req createDocumentRequest
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_body", err.Error())
		return
	}
	req.Title = strings.TrimSpace(req.Title)
	req.Filename = strings.TrimSpace(req.Filename)
	req.MimeType = strings.ToLower(strings.TrimSpace(req.MimeType))

	if req.Title == "" {
		writeError(w, http.StatusBadRequest, "invalid_title", "title is required")
		return
	}
	if req.Filename == "" {
		writeError(w, http.StatusBadRequest, "invalid_filename", "filename is required")
		return
	}
	if _, ok := allowedDocumentMimes[req.MimeType]; !ok {
		writeError(w, http.StatusUnsupportedMediaType, "unsupported_mime",
			fmt.Sprintf("mime_type %q is not a supported document format", req.MimeType))
		return
	}
	if req.SizeBytes <= 0 {
		writeError(w, http.StatusBadRequest, "invalid_size", "size_bytes must be > 0")
		return
	}
	if req.SizeBytes > h.cfg.DocumentMaxBytes {
		writeError(w, http.StatusRequestEntityTooLarge, "file_too_large",
			fmt.Sprintf("size_bytes %d exceeds max %d", req.SizeBytes, h.cfg.DocumentMaxBytes))
		return
	}

	id := uuid.New()
	objectKey := storage.ObjectKeyForDocument(tenantID, id, req.Filename)
	uploadedBy, _ := middleware.UserFromContext(r.Context())

	d, err := database.CreateDocument(r.Context(), h.db, database.CreateDocumentParams{
		ID:         id,
		TenantID:   tenantID,
		UploadedBy: uploadedBy,
		Title:      req.Title,
		ObjectKey:  objectKey,
		MimeType:   req.MimeType,
		SizeBytes:  &req.SizeBytes,
	})
	if err != nil {
		h.logger.Error("create_document_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "create_failed", "could not create document")
		return
	}
	writeJSON(w, http.StatusCreated, d)
}

func (h *Handlers) ListDocuments(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	q := r.URL.Query()
	limit := parseInt32(q.Get("limit"), 50)
	offset := parseInt32(q.Get("offset"), 0)
	rows, err := database.ListDocuments(r.Context(), h.db, tenantID, limit, offset)
	if err != nil {
		h.logger.Error("list_documents_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "list_failed", "could not list documents")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"documents": rows,
		"count":     len(rows),
		"limit":     limit,
		"offset":    offset,
	})
}

func (h *Handlers) GetDocument(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_id", "id must be a UUID")
		return
	}
	d, err := database.GetDocument(r.Context(), h.db, id, tenantID)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "document not found")
		return
	}
	if err != nil {
		h.logger.Error("get_document_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "get_failed", "could not load document")
		return
	}
	writeJSON(w, http.StatusOK, d)
}

func (h *Handlers) DeleteDocument(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_id", "id must be a UUID")
		return
	}
	if err := database.DeleteDocument(r.Context(), h.db, id, tenantID); err != nil {
		if errors.Is(err, database.ErrNotFound) {
			writeError(w, http.StatusNotFound, "not_found", "document not found")
			return
		}
		h.logger.Error("delete_document_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "delete_failed", "could not delete document")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handlers) DocumentUploadURL(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_id", "id must be a UUID")
		return
	}
	d, err := database.GetDocument(r.Context(), h.db, id, tenantID)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "document not found")
		return
	}
	if err != nil {
		h.logger.Error("get_document_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "get_failed", "could not load document")
		return
	}
	if d.ObjectKey == nil || d.MimeType == nil {
		writeError(w, http.StatusConflict, "invalid_state", "document has no upload target")
		return
	}
	uploadURL, err := h.storage.PresignPut(
		r.Context(), *d.ObjectKey, *d.MimeType, h.cfg.PresignTTL,
	)
	if err != nil {
		h.logger.Error("presign_failed", "error", err, "object_key", d.ObjectKey)
		writeError(w, http.StatusInternalServerError, "presign_failed", "could not presign upload URL")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"upload_url": uploadURL,
		"object_key": *d.ObjectKey,
		"mime_type":  *d.MimeType,
		"expires_at": time.Now().UTC().Add(h.cfg.PresignTTL),
	})
}

func (h *Handlers) DocumentUploaded(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_id", "id must be a UUID")
		return
	}
	d, err := database.GetDocument(r.Context(), h.db, id, tenantID)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "document not found")
		return
	}
	if err != nil {
		h.logger.Error("get_document_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "get_failed", "could not load document")
		return
	}
	if d.ObjectKey == nil {
		writeError(w, http.StatusConflict, "invalid_state", "document has no upload target")
		return
	}

	info, err := h.storage.Stat(r.Context(), *d.ObjectKey)
	if err != nil {
		h.logger.Error("stat_object_failed", "error", err, "object_key", *d.ObjectKey)
		writeError(w, http.StatusInternalServerError, "stat_failed", "could not verify object in storage")
		return
	}
	if !info.Exists {
		writeError(w, http.StatusConflict, "not_uploaded",
			"object not found in storage; upload via the presigned URL first")
		return
	}

	payload, err := json.Marshal(map[string]any{
		"document_id": d.ID.String(),
		"tenant_id":   tenantID.String(),
		"object_key":  *d.ObjectKey,
		"mime_type":   derefString(d.MimeType),
		"size_bytes":  info.Size,
		"etag":        info.ETag,
	})
	if err != nil {
		h.logger.Error("marshal_payload_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "internal_error", "could not encode job payload")
		return
	}
	result, err := database.ConfirmDocumentUploaded(
		r.Context(), h.db,
		database.ConfirmDocumentUploadedParams{
			ID:             id,
			TenantID:       tenantID,
			JobPayload:     payload,
			IdempotencyKey: fmt.Sprintf("document:%s:embed", d.ID.String()),
			MaxAttempts:    h.cfg.AIJobMaxAttempts,
		},
	)
	if errors.Is(err, database.ErrInvalidState) {
		writeError(w, http.StatusConflict, "invalid_state",
			"document cannot be confirmed from its current status")
		return
	}
	if err != nil {
		h.logger.Error("enqueue_embed_failed", "error", err, "document_id", d.ID)
		writeError(w, http.StatusInternalServerError, "confirm_failed", "could not confirm upload")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"document": result.Document,
		"job": map[string]any{
			"id":     result.Job.ID,
			"type":   result.Job.Type,
			"status": result.Job.Status,
		},
	})
}

func derefString(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
