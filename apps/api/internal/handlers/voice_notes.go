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

// allowedAudioMimes is the conservative MVP set. Add formats here as we
// confirm the transcription provider supports them.
var allowedAudioMimes = map[string]struct{}{
	"audio/mpeg":  {}, // .mp3
	"audio/mp3":   {}, // some clients send this non-canonical type
	"audio/mp4":   {}, // .m4a
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

// CreateVoiceNote: POST /v1/voice-notes
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

	// Pre-allocate the voice-note id so we can build the object key before insert.
	id := uuid.New()
	objectKey := storage.ObjectKeyForVoiceNote(tenantID, id, req.Filename)

	v, err := database.CreateVoiceNote(r.Context(), h.db, database.CreateVoiceNoteParams{
		TenantID:  tenantID,
		ObjectKey: objectKey,
		MimeType:  req.MimeType,
		SizeBytes: &req.SizeBytes,
		Status:    "pending_upload",
	})
	if err != nil {
		h.logger.Error("create_voice_note_failed", "error", err, "tenant_id", tenantID)
		writeError(w, http.StatusInternalServerError, "create_failed", "could not create voice note")
		return
	}

	writeJSON(w, http.StatusCreated, toVoiceNoteResponse(v))
}

// ListVoiceNotes: GET /v1/voice-notes
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

// GetVoiceNote: GET /v1/voice-notes/{id}
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

// VoiceNoteUploadURL: POST /v1/voice-notes/{id}/upload-url
// Returns a presigned PUT URL the client uses to upload audio bytes directly
// to MinIO/S3, and enqueues a transcribe job in the same request.
//
// TODO: in a real flow, transcribe should be enqueued on an upload-confirmation
// callback (or a server-side HEAD check) rather than at presign time. For MVP
// the worker uses a fake transcription so the ordering doesn't matter yet.
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

	uploadURL, err := h.storage.PresignPut(r.Context(), v.ObjectKey, v.MimeType, h.cfg.PresignTTL)
	if err != nil {
		h.logger.Error("presign_failed", "error", err, "object_key", v.ObjectKey)
		writeError(w, http.StatusInternalServerError, "presign_failed", "could not presign upload URL")
		return
	}
	expiresAt := time.Now().UTC().Add(h.cfg.PresignTTL)

	// Enqueue the transcribe job. Idempotent on (tenant_id, idempotency_key)
	// so repeated calls to this endpoint do not pile up duplicate jobs.
	payload, err := json.Marshal(map[string]any{
		"voice_note_id": v.ID.String(),
		"tenant_id":     tenantID.String(),
		"object_key":    v.ObjectKey,
		"mime_type":     v.MimeType,
	})
	if err != nil {
		h.logger.Error("marshal_payload_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "internal_error", "could not encode job payload")
		return
	}
	job, err := database.EnqueueAIJob(r.Context(), h.db, database.EnqueueAIJobParams{
		TenantID:       tenantID,
		Type:           "transcribe",
		Payload:        payload,
		IdempotencyKey: fmt.Sprintf("voice-note:%s:transcribe", v.ID.String()),
		MaxAttempts:    5,
	})
	if err != nil {
		h.logger.Error("enqueue_transcribe_failed", "error", err, "voice_note_id", v.ID)
		writeError(w, http.StatusInternalServerError, "enqueue_failed", "could not enqueue transcribe job")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"upload_url": uploadURL,
		"object_key": v.ObjectKey,
		"mime_type":  v.MimeType,
		"expires_at": expiresAt,
		"job": map[string]any{
			"id":     job.ID,
			"type":   job.Type,
			"status": job.Status,
		},
	})
}
