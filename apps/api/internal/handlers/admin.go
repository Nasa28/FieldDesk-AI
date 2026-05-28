package handlers

import (
	"encoding/base64"
	"encoding/json"
	"net/http"
	"strconv"
	"time"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/middleware"
	"github.com/google/uuid"
)

const (
	maxLookbackDays    = 366
	defaultLookbackDay = 7
)

// parseWindow reads `from` and `to` query params (RFC3339) and returns a closed-open
// [start, end) window. Defaults: end = now, start = end - 7 days. Caps the lookback
// at 1 year so an unbounded query can't scan the whole table.
func parseWindow(q map[string][]string) (database.TimeWindow, error) {
	now := time.Now().UTC()
	end := now
	if vs, ok := q["to"]; ok && len(vs) > 0 && vs[0] != "" {
		t, err := time.Parse(time.RFC3339, vs[0])
		if err != nil {
			return database.TimeWindow{}, errBadTimeRange
		}
		end = t.UTC()
	}
	start := end.AddDate(0, 0, -defaultLookbackDay)
	if vs, ok := q["from"]; ok && len(vs) > 0 && vs[0] != "" {
		t, err := time.Parse(time.RFC3339, vs[0])
		if err != nil {
			return database.TimeWindow{}, errBadTimeRange
		}
		start = t.UTC()
	}
	if !start.Before(end) {
		return database.TimeWindow{}, errBadTimeRange
	}
	if end.Sub(start) > time.Duration(maxLookbackDays)*24*time.Hour {
		return database.TimeWindow{}, errBadTimeRange
	}
	return database.TimeWindow{Start: start, End: end}, nil
}

var errBadTimeRange = badRequestError("invalid_time_range")

type badRequestError string

func (e badRequestError) Error() string { return string(e) }

// Costs returns the cost rollup + per-kind + per-model breakdowns for the window.
func (h *Handlers) Costs(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	window, err := parseWindow(r.URL.Query())
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_time_range", "from/to must be RFC3339 and span <= 366 days")
		return
	}

	rollup, err := database.CostRollupForTenant(r.Context(), h.db, tenantID, window)
	if err != nil {
		h.logger.Error("costs_rollup_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "rollup_failed", "could not compute cost rollup")
		return
	}
	byKind, err := database.CostByKind(r.Context(), h.db, tenantID, window)
	if err != nil {
		h.logger.Error("costs_by_kind_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "rollup_failed", "could not compute per-kind cost")
		return
	}
	byModel, err := database.CostByModel(r.Context(), h.db, tenantID, window)
	if err != nil {
		h.logger.Error("costs_by_model_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "rollup_failed", "could not compute per-model cost")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"window":   windowResponse(window),
		"rollup":   rollup,
		"by_kind":  byKind,
		"by_model": byModel,
	})
}

// AdminMetrics combines job counters and latency percentiles into a single dashboard payload.
func (h *Handlers) AdminMetrics(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	window, err := parseWindow(r.URL.Query())
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_time_range", "from/to must be RFC3339 and span <= 366 days")
		return
	}

	jobs, err := database.JobMetricsForTenant(r.Context(), h.db, tenantID, window)
	if err != nil {
		h.logger.Error("admin_metrics_jobs_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "metrics_failed", "could not compute job metrics")
		return
	}
	latency, err := database.LatencyPercentilesByKind(r.Context(), h.db, tenantID, window)
	if err != nil {
		h.logger.Error("admin_metrics_latency_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "metrics_failed", "could not compute latency")
		return
	}

	unsuccessfulTerminal := jobs.FailedJobs + jobs.NeedsReviewJobs
	terminal := jobs.SucceededJobs + unsuccessfulTerminal
	writeJSON(w, http.StatusOK, map[string]any{
		"window":                windowResponse(window),
		"jobs":                  jobs,
		"job_success_rate":      ratio(jobs.SucceededJobs, terminal),
		"job_failure_rate":      ratio(unsuccessfulTerminal, terminal),
		"job_needs_review_rate": ratio(jobs.NeedsReviewJobs, terminal),
		"job_retry_rate":        ratio(jobs.RetriedJobs, jobs.TotalJobs),
		"latency_by_kind":       latency,
	})
}

// AdminFailures lists failed provider calls plus failed/needs-review/stuck jobs.
func (h *Handlers) AdminFailures(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	window, err := parseWindow(r.URL.Query())
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_time_range", "from/to must be RFC3339 and span <= 366 days")
		return
	}
	cursor, err := parseCursor(r.URL.Query().Get("cursor"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_cursor", "cursor must be RFC3339")
		return
	}
	q := r.URL.Query()
	limit := parseInt32(q.Get("limit"), 50)
	if limit > 200 {
		limit = 200
	}

	items, err := database.ListFailureFeed(r.Context(), h.db, database.ListFailureFeedParams{
		TenantID: tenantID,
		Window:   window,
		Kind:     q.Get("kind"),
		Provider: q.Get("provider"),
		Cursor:   cursor,
		Limit:    limit,
	})
	if err != nil {
		h.logger.Error("admin_failures_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "list_failed", "could not list failures")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"window":      windowResponse(window),
		"items":       items,
		"count":       len(items),
		"next_cursor": nextFailureCursor(items),
	})
}

// ListModelLogs paginates ai_model_calls (the raw provider-call log).
func (h *Handlers) ListModelLogs(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	window, err := parseWindow(r.URL.Query())
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_time_range", "from/to must be RFC3339 and span <= 366 days")
		return
	}
	cursor, err := parseCursor(r.URL.Query().Get("cursor"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_cursor", "cursor must be RFC3339")
		return
	}

	q := r.URL.Query()
	successFilter := q.Get("success")
	switch successFilter {
	case "", "all", "success", "failed":
	default:
		writeError(w, http.StatusBadRequest, "invalid_filter", "success must be one of: all, success, failed")
		return
	}
	limit := parseInt32(q.Get("limit"), 100)
	if limit > 500 {
		limit = 500
	}

	items, err := database.ListModelCalls(r.Context(), h.db, database.ListModelCallsParams{
		TenantID:      tenantID,
		Window:        window,
		Kind:          q.Get("kind"),
		Provider:      q.Get("provider"),
		SuccessFilter: successFilter,
		Cursor:        cursor,
		Limit:         limit,
	})
	if err != nil {
		h.logger.Error("list_model_logs_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "list_failed", "could not list model logs")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"window":      windowResponse(window),
		"items":       items,
		"count":       len(items),
		"next_cursor": nextCursor(items),
	})
}

// CostsByTicket returns the top-N most expensive tickets in the window
// plus the tenant-wide avg cost per attributed ticket. Pairs the per-
// ticket aggregate (the long-tail-skewing top-N) with the average (the
// dashboard headline) so the UI can render both from one round-trip.
func (h *Handlers) CostsByTicket(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	window, err := parseWindow(r.URL.Query())
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_time_range", "from/to must be RFC3339 and span <= 366 days")
		return
	}
	limit := parseTopNLimit(r.URL.Query().Get("limit"))

	top, err := database.MostExpensiveTickets(r.Context(), h.db, tenantID, window, limit)
	if err != nil {
		h.logger.Error("costs_by_ticket_top_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "rollup_failed", "could not compute per-ticket cost")
		return
	}
	summary, err := database.CostPerTicketSummaryForTenant(r.Context(), h.db, tenantID, window)
	if err != nil {
		h.logger.Error("costs_by_ticket_summary_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "rollup_failed", "could not compute avg cost per ticket")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"window":                  windowResponse(window),
		"ticket_count":            summary.TicketCount,
		"avg_cost_per_ticket_usd": summary.AvgCostPerTicketUSD,
		"top_tickets":             top,
	})
}

const (
	defaultTopNLimit = 10
	maxTopNLimit     = 100
)

// parseTopNLimit clamps the ?limit= param to a small safe range. We don't
// 400 on bad input here — an unparseable string just falls back to the
// default, since the endpoint is operator-facing and the only thing that
// could break is "the user typoed the URL bar."
func parseTopNLimit(raw string) int {
	if raw == "" {
		return defaultTopNLimit
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n <= 0 {
		return defaultTopNLimit
	}
	if n > maxTopNLimit {
		return maxTopNLimit
	}
	return n
}

func windowResponse(w database.TimeWindow) map[string]any {
	return map[string]any{
		"from": w.Start.Format(time.RFC3339),
		"to":   w.End.Format(time.RFC3339),
	}
}

// ratio returns numerator/denominator as a fraction, or 0 when denominator is zero.
// Callers pass terminal counts (success+fail) to avoid skewing the rate with in-flight jobs.
func ratio(numerator, denominator int64) float64 {
	if denominator <= 0 {
		return 0
	}
	return float64(numerator) / float64(denominator)
}

type cursorPayload struct {
	CreatedAt time.Time `json:"created_at"`
	ID        uuid.UUID `json:"id"`
}

func parseCursor(raw string) (*database.LogCursor, error) {
	if raw == "" {
		return nil, nil
	}
	if decoded, err := base64.RawURLEncoding.DecodeString(raw); err == nil {
		var payload cursorPayload
		if err := json.Unmarshal(decoded, &payload); err == nil &&
			!payload.CreatedAt.IsZero() && payload.ID != uuid.Nil {
			return &database.LogCursor{CreatedAt: payload.CreatedAt.UTC(), ID: payload.ID}, nil
		}
	}
	t, err := time.Parse(time.RFC3339Nano, raw)
	if err != nil {
		// Tolerate plain RFC3339 too.
		t2, err2 := time.Parse(time.RFC3339, raw)
		if err2 != nil {
			return nil, err
		}
		t = t2
	}
	return &database.LogCursor{
		CreatedAt: t.UTC(),
		ID:        uuid.MustParse("ffffffff-ffff-ffff-ffff-ffffffffffff"),
	}, nil
}

func nextCursor(items []database.ModelCallRow) string {
	if len(items) == 0 {
		return ""
	}
	last := items[len(items)-1]
	return encodeCursor(last.CreatedAt, last.ID)
}

func nextFailureCursor(items []database.FailureFeedRow) string {
	if len(items) == 0 {
		return ""
	}
	last := items[len(items)-1]
	return encodeCursor(last.CreatedAt, last.ID)
}

func encodeCursor(createdAt time.Time, id uuid.UUID) string {
	payload, err := json.Marshal(cursorPayload{CreatedAt: createdAt.UTC(), ID: id})
	if err != nil {
		return ""
	}
	return base64.RawURLEncoding.EncodeToString(payload)
}
