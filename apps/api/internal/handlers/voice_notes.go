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

var allowedAudioMimes = map[string]struct{}{
	"audio/mpeg":  {},
	"audio/mp3":   {},
	"audio/mp4":   {},
	"audio/m4a":   {},
	"audio/wav":   {},
	"audio/x-wav": {},
	"audio/webm":  {},
	"audio/ogg":   {},
	"audio/flac":  {},
}

type createVoiceNoteRequest struct {
	Filename  string `json:"filename"`
	MimeType  string `json:"mime_type"`
	SizeBytes int64  `json:"size_bytes"`
}

type voiceNoteResponse struct {
	ID         uuid.UUID  `json:"id"`
	TenantID   uuid.UUID  `json:"tenant_id"`
	UploadedBy *uuid.UUID `json:"uploaded_by,omitempty"`
	ObjectKey  string     `json:"object_key"`
	MimeType   string     `json:"mime_type"`
	SizeBytes  *int64     `json:"size_bytes,omitempty"`
	Status     string     `json:"status"`
	CreatedAt  time.Time  `json:"created_at"`
	UpdatedAt  time.Time  `json:"updated_at"`
}

func toVoiceNoteResponse(v database.VoiceNote) voiceNoteResponse {
	return voiceNoteResponse{
		ID:         v.ID,
		TenantID:   v.TenantID,
		UploadedBy: v.UploadedBy,
		ObjectKey:  v.ObjectKey,
		MimeType:   v.MimeType,
		SizeBytes:  v.SizeBytes,
		Status:     v.Status,
		CreatedAt:  v.CreatedAt,
		UpdatedAt:  v.UpdatedAt,
	}
}

func (h *Handlers) CreateVoiceNote(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}

	var req createVoiceNoteRequest
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_body", err.Error())
		return
	}
	req.Filename = strings.TrimSpace(req.Filename)
	req.MimeType = strings.ToLower(strings.TrimSpace(req.MimeType))

	if req.Filename == "" {
		writeError(w, http.StatusBadRequest, "invalid_filename", "filename is required")
		return
	}
	if _, ok := allowedAudioMimes[req.MimeType]; !ok {
		writeError(w, http.StatusUnsupportedMediaType, "unsupported_mime",
			fmt.Sprintf("mime_type %q is not a supported audio format", req.MimeType))
		return
	}
	if req.SizeBytes <= 0 {
		writeError(w, http.StatusBadRequest, "invalid_size", "size_bytes must be > 0")
		return
	}
	if req.SizeBytes > h.cfg.VoiceNoteMaxBytes {
		writeError(w, http.StatusRequestEntityTooLarge, "file_too_large",
			fmt.Sprintf("size_bytes %d exceeds max %d", req.SizeBytes, h.cfg.VoiceNoteMaxBytes))
		return
	}

	id := uuid.New()
	objectKey := storage.ObjectKeyForVoiceNote(tenantID, id, req.Filename)
	uploadedBy, _ := middleware.UserFromContext(r.Context())

	v, err := database.CreateVoiceNote(r.Context(), h.db, database.CreateVoiceNoteParams{
		ID:         id,
		TenantID:   tenantID,
		UploadedBy: uploadedBy,
		ObjectKey:  objectKey,
		MimeType:   req.MimeType,
		SizeBytes:  &req.SizeBytes,
		Status:     "pending_upload",
	})
	if err != nil {
		h.logger.Error("create_voice_note_failed", "error", err, "tenant_id", tenantID)
		writeError(w, http.StatusInternalServerError, "create_failed", "could not create voice note")
		return
	}

	writeJSON(w, http.StatusCreated, toVoiceNoteResponse(v))
}

func (h *Handlers) ListVoiceNotes(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}

	rows, err := database.ListVoiceNotes(r.Context(), h.db, tenantID, 50)
	if err != nil {
		h.logger.Error("list_voice_notes_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "list_failed", "could not list voice notes")
		return
	}

	resp := make([]voiceNoteResponse, 0, len(rows))
	for _, v := range rows {
		resp = append(resp, toVoiceNoteResponse(v))
	}
	writeJSON(w, http.StatusOK, map[string]any{"voice_notes": resp})
}

func (h *Handlers) GetVoiceNote(w http.ResponseWriter, r *http.Request) {
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

	v, err := database.GetVoiceNote(r.Context(), h.db, id, tenantID)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "voice note not found")
		return
	}
	if err != nil {
		h.logger.Error("get_voice_note_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "get_failed", "could not load voice note")
		return
	}
	writeJSON(w, http.StatusOK, toVoiceNoteResponse(v))
}

func (h *Handlers) VoiceNoteUploadURL(w http.ResponseWriter, r *http.Request) {
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

	v, err := database.GetVoiceNote(r.Context(), h.db, id, tenantID)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "voice note not found")
		return
	}
	if err != nil {
		h.logger.Error("get_voice_note_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "get_failed", "could not load voice note")
		return
	}
	if v.Status != "pending_upload" {
		writeError(w, http.StatusConflict, "invalid_state", "voice note is no longer accepting uploads")
		return
	}

	uploadURL, err := h.storage.PresignPut(r.Context(), v.ObjectKey, v.MimeType, h.cfg.PresignTTL)
	if err != nil {
		h.logger.Error("presign_failed", "error", err, "object_key", v.ObjectKey)
		writeError(w, http.StatusInternalServerError, "presign_failed", "could not presign upload URL")
		return
	}
	expiresAt := time.Now().UTC().Add(h.cfg.PresignTTL)

	writeJSON(w, http.StatusOK, map[string]any{
		"upload_url": uploadURL,
		"object_key": v.ObjectKey,
		"mime_type":  v.MimeType,
		"expires_at": expiresAt,
	})
}

func (h *Handlers) VoiceNoteUploaded(w http.ResponseWriter, r *http.Request) {
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

	v, err := database.GetVoiceNote(r.Context(), h.db, id, tenantID)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "voice note not found")
		return
	}
	if err != nil {
		h.logger.Error("get_voice_note_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "get_failed", "could not load voice note")
		return
	}

	info, err := h.storage.Stat(r.Context(), v.ObjectKey)
	if err != nil {
		h.logger.Error("stat_object_failed", "error", err, "object_key", v.ObjectKey)
		writeError(w, http.StatusInternalServerError, "stat_failed", "could not verify object in storage")
		return
	}
	if !info.Exists {
		writeError(w, http.StatusConflict, "not_uploaded",
			"object not found in storage; upload via the presigned URL first")
		return
	}
	if err := validateUploadedObject(v, info); err != nil {
		writeError(w, http.StatusConflict, "upload_mismatch", err.Error())
		return
	}

	payload, err := json.Marshal(map[string]any{
		"voice_note_id": v.ID.String(),
		"tenant_id":     tenantID.String(),
		"object_key":    v.ObjectKey,
		"mime_type":     v.MimeType,
		"size_bytes":    info.Size,
		"content_type":  info.ContentType,
		"etag":          info.ETag,
	})
	if err != nil {
		h.logger.Error("marshal_payload_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "internal_error", "could not encode job payload")
		return
	}
	result, err := database.ConfirmVoiceNoteUploaded(r.Context(), h.db, database.ConfirmVoiceNoteUploadedParams{
		ID:             id,
		TenantID:       tenantID,
		JobPayload:     payload,
		IdempotencyKey: fmt.Sprintf("voice-note:%s:transcribe", v.ID.String()),
		MaxAttempts:    h.cfg.AIJobMaxAttempts,
	})
	if errors.Is(err, database.ErrInvalidState) {
		writeError(w, http.StatusConflict, "invalid_state", "voice note cannot be confirmed from its current status")
		return
	}
	if err != nil {
		h.logger.Error("enqueue_transcribe_failed", "error", err, "voice_note_id", v.ID)
		writeError(w, http.StatusInternalServerError, "confirm_failed", "could not confirm upload")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"voice_note": toVoiceNoteResponse(result.VoiceNote),
		"job": map[string]any{
			"id":     result.Job.ID,
			"type":   result.Job.Type,
			"status": result.Job.Status,
		},
	})
}

func validateUploadedObject(v database.VoiceNote, info storage.ObjectInfo) error {
	if v.SizeBytes != nil && info.Size != *v.SizeBytes {
		return fmt.Errorf("uploaded object size %d does not match declared size %d", info.Size, *v.SizeBytes)
	}
	if info.ContentType == "" {
		return nil
	}
	got := strings.ToLower(strings.TrimSpace(strings.Split(info.ContentType, ";")[0]))
	want := strings.ToLower(strings.TrimSpace(v.MimeType))
	if got != "" && want != "" && got != want {
		return fmt.Errorf("uploaded object content type %q does not match declared mime_type %q", got, want)
	}
	return nil
}
