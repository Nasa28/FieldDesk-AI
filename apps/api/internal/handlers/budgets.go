package handlers

import (
	"errors"
	"math"
	"net/http"

	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/middleware"
)

// budgetPayload is the body shape for PUT /v1/admin/budgets.
// All limit fields are pointers so the caller can either set, change, or
// clear (null) each cap independently. pause_on_exceeded defaults to true
// when omitted — the safe default is "stop spending when over."
type budgetPayload struct {
	DailyBudgetUSD   *float64 `json:"daily_budget_usd"`
	MonthlyBudgetUSD *float64 `json:"monthly_budget_usd"`
	MaxCostPerTicket *float64 `json:"max_cost_per_ticket"`
	PauseOnExceeded  *bool    `json:"pause_on_exceeded"`
}

// GetBudgets returns the budget view for the authenticated tenant. A tenant
// with no budget configured still returns a row (NULL limits, false overs).
func (h *Handlers) GetBudgets(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	usage, err := database.GetBudgetUsage(r.Context(), h.db, tenantID)
	if errors.Is(err, database.ErrNotFound) {
		writeError(w, http.StatusNotFound, "tenant_not_found", "tenant does not exist")
		return
	}
	if err != nil {
		h.logger.Error("get_budgets_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "budget_read_failed", "could not read budget")
		return
	}
	writeJSON(w, http.StatusOK, usage)
}

// PutBudgets upserts the tenant's budget row. Returns the resulting budget +
// fresh usage view so the UI can re-render without a second fetch.
func (h *Handlers) PutBudgets(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := middleware.TenantFromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing_tenant", "tenant context missing")
		return
	}
	var body budgetPayload
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_body", err.Error())
		return
	}
	if err := validateBudgetPayload(body); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_budget", err.Error())
		return
	}

	pauseOnExceeded := true
	if body.PauseOnExceeded != nil {
		pauseOnExceeded = *body.PauseOnExceeded
	}

	_, err := database.UpsertBudget(r.Context(), h.db, database.UpsertBudgetParams{
		TenantID:         tenantID,
		DailyBudgetUSD:   body.DailyBudgetUSD,
		MonthlyBudgetUSD: body.MonthlyBudgetUSD,
		MaxCostPerTicket: body.MaxCostPerTicket,
		PauseOnExceeded:  pauseOnExceeded,
	})
	if err != nil {
		h.logger.Error("upsert_budget_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "budget_write_failed", "could not save budget")
		return
	}
	usage, err := database.GetBudgetUsage(r.Context(), h.db, tenantID)
	if err != nil {
		h.logger.Error("get_budgets_after_upsert_failed", "error", err)
		writeError(w, http.StatusInternalServerError, "budget_read_failed", "saved but could not re-read budget")
		return
	}
	writeJSON(w, http.StatusOK, usage)
}

// validateBudgetPayload rejects negative / NaN / Inf limits. Zero is a valid
// cap (means "no spend allowed") and is left to the operator.
func validateBudgetPayload(p budgetPayload) error {
	if err := validateLimit("daily_budget_usd", p.DailyBudgetUSD); err != nil {
		return err
	}
	if err := validateLimit("monthly_budget_usd", p.MonthlyBudgetUSD); err != nil {
		return err
	}
	if err := validateLimit("max_cost_per_ticket", p.MaxCostPerTicket); err != nil {
		return err
	}
	if p.DailyBudgetUSD != nil && p.MonthlyBudgetUSD != nil && *p.DailyBudgetUSD > *p.MonthlyBudgetUSD {
		return errors.New("daily_budget_usd cannot exceed monthly_budget_usd")
	}
	return nil
}

func validateLimit(name string, v *float64) error {
	if v == nil {
		return nil
	}
	if math.IsNaN(*v) || math.IsInf(*v, 0) {
		return errors.New(name + " must be a finite number")
	}
	if *v < 0 {
		return errors.New(name + " cannot be negative")
	}
	return nil
}
