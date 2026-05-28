package handlers

import (
	"errors"
	"net/http"
	"strconv"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/middleware"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

func (h *Handlers) ListTickets(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}

	q := r.URL.Query()
	limit := parseInt32(q.Get("limit"), 50)
	offset := parseInt32(q.Get("offset"), 0)

	tickets, err := database.ListTickets(r.Context(), h.db, database.ListTicketsParams{
		TenantID: tenantID,
		Status:   q.Get("status"),
		Limit:    limit,
		Offset:   offset,
	})
	if err != nil {
		h.logger.Error("list_tickets_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "list_failed", "could not list tickets")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"tickets": tickets,
		"limit":   limit,
		"offset":  offset,
	})
}

func (h *Handlers) GetTicket(w http.ResponseWriter, r *http.Request) {
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
	t, err := database.GetTicket(r.Context(), h.db, id, tenantID)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "ticket not found")
		return
	}
	if err != nil {
		h.logger.Error("get_ticket_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "get_failed", "could not load ticket")
		return
	}
	writeJSON(w, http.StatusOK, t)
}

func (h *Handlers) UpdateTicket(w http.ResponseWriter, r *http.Request) {
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
	var body database.TicketCorrection
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_body", err.Error())
		return
	}
	if !body.HasPatchField() {
		writeError(w, http.StatusBadRequest, "invalid_patch", "request must include at least one ticket field")
		return
	}
	t, err := database.UpdateTicket(r.Context(), h.db, id, tenantID, body)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "ticket not found")
		return
	}
	if errors.Is(err, database.ErrInvalidState) {
		writeError(w, http.StatusConflict, "invalid_state", "ticket can only be edited while draft, needs_review, or rejected")
		return
	}
	if err != nil {
		h.logger.Error("update_ticket_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "update_failed", "could not update ticket")
		return
	}
	writeJSON(w, http.StatusOK, t)
}

func (h *Handlers) ApproveTicket(w http.ResponseWriter, r *http.Request) {
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
	approvedBy, _ := middleware.UserFromContext(r.Context())
	t, err := database.ApproveTicket(r.Context(), h.db, id, tenantID, approvedBy)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "ticket not found")
		return
	}
	if errors.Is(err, database.ErrInvalidState) {
		writeError(w, http.StatusConflict, "invalid_state", "only draft tickets can be approved")
		return
	}
	if err != nil {
		h.logger.Error("approve_ticket_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "approve_failed", "could not approve ticket")
		return
	}
	writeJSON(w, http.StatusOK, t)
}

type rejectTicketRequest struct {
	Reason string `json:"reason"`
}

func (h *Handlers) RejectTicket(w http.ResponseWriter, r *http.Request) {
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
	var body rejectTicketRequest
	if r.ContentLength > 0 {
		if err := decodeJSON(r, &body); err != nil {
			writeError(w, http.StatusBadRequest, "invalid_body", err.Error())
			return
		}
	}
	t, err := database.RejectTicket(r.Context(), h.db, id, tenantID, body.Reason)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "ticket not found")
		return
	}
	if errors.Is(err, database.ErrInvalidState) {
		writeError(w, http.StatusConflict, "invalid_state", "only draft or needs_review tickets can be rejected")
		return
	}
	if err != nil {
		h.logger.Error("reject_ticket_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "reject_failed", "could not reject ticket")
		return
	}
	writeJSON(w, http.StatusOK, t)
}

// GetTicketRecommendations returns the most recent ticket_recommendations
// row attached to a ticket — the structured RAG-synthesis output produced
// by the draft_ticket job after the rag job retrieves chunks for the
// ticket. Returns 404 when synthesis hasn't completed yet; the client
// distinguishes "pending" from a real error by treating the 404 as
// "still working" (see the Suggestions component on the web side).
func (h *Handlers) GetTicketRecommendations(w http.ResponseWriter, r *http.Request) {
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
	rec, err := database.GetLatestRecommendationForTicket(r.Context(), h.db, id, tenantID)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "no recommendations yet for this ticket")
		return
	}
	if err != nil {
		h.logger.Error("get_ticket_recommendations_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "load_failed", "could not load recommendations")
		return
	}
	writeJSON(w, http.StatusOK, rec)
}

func parseInt32(s string, fallback int32) int32 {
	if s == "" {
		return fallback
	}
	n, err := strconv.ParseInt(s, 10, 32)
	if err != nil || n < 0 {
		return fallback
	}
	return int32(n)
}
