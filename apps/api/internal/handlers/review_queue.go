package handlers

import (
	"errors"
	"net/http"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/middleware"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

func (h *Handlers) ListReviewQueue(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}

	q := r.URL.Query()
	items, err := database.ListOpenHumanReviews(r.Context(), h.db, database.ListReviewsParams{
		TenantID: tenantID,
		Status:   q.Get("status"),
		Reason:   q.Get("reason"),
		Limit:    parseInt32(q.Get("limit"), 50),
		Offset:   parseInt32(q.Get("offset"), 0),
	})
	if err != nil {
		h.logger.Error("list_review_queue_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "list_failed", "could not list review queue")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"items":  items,
		"count":  len(items),
		"limit":  parseInt32(q.Get("limit"), 50),
		"offset": parseInt32(q.Get("offset"), 0),
	})
}

type resolveReviewRequest struct {
	Correction database.TicketCorrection `json:"correction"`
	Notes      *string                   `json:"notes,omitempty"`
}

func (h *Handlers) ResolveReview(w http.ResponseWriter, r *http.Request) {
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

	var body resolveReviewRequest
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_body", err.Error())
		return
	}

	result, err := database.ResolveHumanReview(r.Context(), h.db, database.ResolveHumanReviewParams{
		ReviewID:   id,
		TenantID:   tenantID,
		Correction: body.Correction,
		Notes:      body.Notes,
	})
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "review not found")
		return
	}
	if errors.Is(err, database.ErrInvalidState) {
		writeError(w, http.StatusConflict, "already_resolved", "review is not in 'open' state")
		return
	}
	if errors.Is(err, database.ErrInvalidCorrection) {
		writeError(w, http.StatusBadRequest, "invalid_correction", "correction must include at least one ticket field")
		return
	}
	if err != nil {
		h.logger.Error("resolve_review_failed", "error", err, "review_id", id)
		writeError(w, http.StatusInternalServerError, "resolve_failed", "could not resolve review")
		return
	}
	writeJSON(w, http.StatusOK, result)
}
