package handlers

import (
	"errors"
	"net/http"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/middleware"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

func (h *Handlers) ListAIJobs(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}

	q := r.URL.Query()
	jobs, err := database.ListAIJobs(r.Context(), h.db, database.ListAIJobsParams{
		TenantID: tenantID,
		Status:   q.Get("status"),
		Type:     q.Get("type"),
		Limit:    parseInt32(q.Get("limit"), 50),
		Offset:   parseInt32(q.Get("offset"), 0),
	})
	if err != nil {
		h.logger.Error("list_ai_jobs_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "list_failed", "could not list AI jobs")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"jobs": jobs})
}

func (h *Handlers) GetAIJob(w http.ResponseWriter, r *http.Request) {
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

	job, err := database.GetAIJob(r.Context(), h.db, id, tenantID)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "AI job not found")
		return
	}
	if err != nil {
		h.logger.Error("get_ai_job_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "get_failed", "could not load AI job")
		return
	}
	attempts, err := database.ListAIJobAttempts(r.Context(), h.db, id, tenantID)
	if err != nil {
		h.logger.Error("list_ai_job_attempts_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "get_failed", "could not load AI job attempts")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"job":      job,
		"attempts": attempts,
	})
}

func (h *Handlers) RetryAIJob(w http.ResponseWriter, r *http.Request) {
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

	job, err := database.RetryAIJob(r.Context(), h.db, id, tenantID, h.cfg.AIJobMaxAttempts)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "AI job not found")
		return
	}
	if errors.Is(err, database.ErrInvalidState) {
		writeError(w, http.StatusConflict, "invalid_state", "only failed or needs_review jobs can be retried")
		return
	}
	if err != nil {
		h.logger.Error("retry_ai_job_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "retry_failed", "could not retry AI job")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{"job": job})
}
