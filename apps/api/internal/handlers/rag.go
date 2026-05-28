package handlers

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/middleware"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

type ragSearchRequest struct {
	QueryText string `json:"query_text"`
	TopK      int    `json:"top_k"`
	Answer    bool   `json:"answer"`
}

// RAGSearch enqueues an ad-hoc retrieval job and returns its id immediately.
// The Go side deliberately does not embed the query itself — that would
// require duplicating the worker's embedding adapter and an Anthropic / OpenAI
// key in this process. Clients poll the existing /v1/ai-jobs/{id} endpoint for
// completion and then read the result via rag_queries (job_id correlated via
// payload).
func (h *Handlers) RAGSearch(w http.ResponseWriter, r *http.Request) {
	h.enqueueAdHocRAG(w, r, false)
}

// RAGAsk is the knowledge-base Q&A path: same retrieval job as /search, plus
// worker-side grounded answer synthesis in ai_jobs.result.answer.
func (h *Handlers) RAGAsk(w http.ResponseWriter, r *http.Request) {
	h.enqueueAdHocRAG(w, r, true)
}

func (h *Handlers) enqueueAdHocRAG(w http.ResponseWriter, r *http.Request, forceAnswer bool) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}

	var req ragSearchRequest
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_body", err.Error())
		return
	}
	req.QueryText = strings.TrimSpace(req.QueryText)
	if req.QueryText == "" {
		writeError(w, http.StatusBadRequest, "invalid_query", "query_text is required")
		return
	}
	if len(req.QueryText) > 4000 {
		writeError(w, http.StatusBadRequest, "query_too_long", "query_text must be <= 4000 chars")
		return
	}
	topK := req.TopK
	if topK <= 0 {
		topK = 5
	}
	if topK > 25 {
		topK = 25
	}
	answer := forceAnswer || req.Answer

	payload, err := json.Marshal(map[string]any{
		"tenant_id":  tenantID.String(),
		"query_text": req.QueryText,
		"top_k":      topK,
		"source":     "ad_hoc",
		"answer":     answer,
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "could not encode payload")
		return
	}

	// Idempotency key includes a content hash of (query, top_k) so two
	// identical requests in flight coalesce, but a different query produces a
	// new job. We use the tenant + query hash; users hitting the same query
	// rapidly get the cached job rather than spawning N copies.
	mode := "search"
	if answer {
		mode = "answer"
	}
	idem := fmt.Sprintf("rag:adhoc:%s:%s:%d:%x",
		mode, tenantID.String(), topK, hashQueryText(req.QueryText))

	job, err := database.EnqueueAIJob(r.Context(), h.db, database.EnqueueAIJobParams{
		TenantID:       tenantID,
		Type:           "rag",
		Payload:        payload,
		IdempotencyKey: idem,
		MaxAttempts:    h.cfg.AIJobMaxAttempts,
	})
	if err != nil {
		h.logger.Error("enqueue_rag_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "enqueue_failed", "could not enqueue rag job")
		return
	}

	// Ad-hoc results land in ai_jobs.result; poll /v1/ai-jobs/{id}. The
	// ticket-bound auto-rag path persists to rag_queries (different shape,
	// queryable via /v1/rag/queries/by-ticket/{id}).
	writeJSON(w, http.StatusAccepted, map[string]any{
		"job_id":  job.ID,
		"status":  job.Status,
		"job_url": fmt.Sprintf("/v1/ai-jobs/%s", job.ID),
		"query": map[string]any{
			"text":   req.QueryText,
			"top_k":  topK,
			"answer": answer,
		},
	})
}

// RAGQueryByTicket returns the most recent rag_queries row attached to the
// given ticket. This is the path the dashboard's ticket page uses for the
// "Related documents" section.
func (h *Handlers) RAGQueryByTicket(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	ticketID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_id", "id must be a UUID")
		return
	}
	q, err := database.GetLatestRAGQueryForTicket(r.Context(), h.db, ticketID, tenantID)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "no rag query yet for this ticket")
		return
	}
	if err != nil {
		h.logger.Error("rag_query_by_ticket_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "load_failed", "could not load rag query")
		return
	}
	writeJSON(w, http.StatusOK, q)
}

// hashQueryText is a small, stable hash for the idempotency-key suffix.
// FNV-1a 64-bit is sufficient — collisions only matter within a tenant for
// a few seconds (the idempotency window).
func hashQueryText(s string) uint64 {
	const (
		offset = 1469598103934665603
		prime  = 1099511628211
	)
	h := uint64(offset)
	for i := 0; i < len(s); i++ {
		h ^= uint64(s[i])
		h *= prime
	}
	return h
}
