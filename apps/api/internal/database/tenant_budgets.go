package database

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

// BudgetUsage mirrors the v_tenant_budget_usage view. Limit columns are nullable
// because "no cap configured" is a valid state — the view returns false for the
// over flags in that case.
type BudgetUsage struct {
	TenantID         uuid.UUID `json:"tenant_id"`
	DailyBudgetUSD   *float64  `json:"daily_budget_usd,omitempty"`
	MonthlyBudgetUSD *float64  `json:"monthly_budget_usd,omitempty"`
	MaxCostPerTicket *float64  `json:"max_cost_per_ticket,omitempty"`
	PauseOnExceeded  bool      `json:"pause_on_exceeded"`
	DailySpendUSD    float64   `json:"daily_spend_usd"`
	MonthlySpendUSD  float64   `json:"monthly_spend_usd"`
	DailyOver        bool      `json:"daily_over"`
	MonthlyOver      bool      `json:"monthly_over"`
}

// GetBudgetUsage returns the budget + current-window spend for a tenant.
// Returns ErrNotFound when the tenant itself does not exist; a tenant with
// no budget row still returns a usage row (with NULL limits).
func GetBudgetUsage(ctx context.Context, db *DB, tenantID uuid.UUID) (BudgetUsage, error) {
	const q = `
		SELECT
			tenant_id,
			daily_budget_usd, monthly_budget_usd, max_cost_per_ticket,
			pause_on_exceeded,
			daily_spend_usd, monthly_spend_usd,
			daily_over, monthly_over
		FROM v_tenant_budget_usage
		WHERE tenant_id = $1
	`
	var (
		u                                   BudgetUsage
		dailyLimit, monthlyLimit, perTicket pgtype.Numeric
		dailySpend, monthlySpend            pgtype.Numeric
	)
	err := db.QueryRow(ctx, q, tenantID).Scan(
		&u.TenantID,
		&dailyLimit, &monthlyLimit, &perTicket,
		&u.PauseOnExceeded,
		&dailySpend, &monthlySpend,
		&u.DailyOver, &u.MonthlyOver,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return BudgetUsage{}, ErrNotFound
	}
	if err != nil {
		return BudgetUsage{}, err
	}
	u.DailyBudgetUSD = numericToFloatPtr(dailyLimit)
	u.MonthlyBudgetUSD = numericToFloatPtr(monthlyLimit)
	u.MaxCostPerTicket = numericToFloatPtr(perTicket)
	u.DailySpendUSD = numericToFloat(dailySpend)
	u.MonthlySpendUSD = numericToFloat(monthlySpend)
	return u, nil
}

// UpsertBudgetParams mirrors the PUT /v1/admin/budgets body. Nil limit fields
// clear the cap (column is NULL). PauseOnExceeded defaults to true at the
// table level — if the caller omits it (HTTP layer should default to true) the
// upsert still writes a concrete boolean.
type UpsertBudgetParams struct {
	TenantID         uuid.UUID
	DailyBudgetUSD   *float64
	MonthlyBudgetUSD *float64
	MaxCostPerTicket *float64
	PauseOnExceeded  bool
}

// TenantBudget is the row in tenant_ai_budgets; the admin handlers return the
// view (BudgetUsage) instead, but the upsert returns the raw row so callers can
// see exactly what was written.
type TenantBudget struct {
	TenantID         uuid.UUID `json:"tenant_id"`
	DailyBudgetUSD   *float64  `json:"daily_budget_usd,omitempty"`
	MonthlyBudgetUSD *float64  `json:"monthly_budget_usd,omitempty"`
	MaxCostPerTicket *float64  `json:"max_cost_per_ticket,omitempty"`
	PauseOnExceeded  bool      `json:"pause_on_exceeded"`
	UpdatedAt        time.Time `json:"updated_at"`
}

func UpsertBudget(ctx context.Context, db *DB, p UpsertBudgetParams) (TenantBudget, error) {
	const q = `
		INSERT INTO tenant_ai_budgets
			(tenant_id, daily_budget_usd, monthly_budget_usd, max_cost_per_ticket, pause_on_exceeded, updated_at)
		VALUES ($1, $2, $3, $4, $5, now())
		ON CONFLICT (tenant_id) DO UPDATE
			SET daily_budget_usd     = EXCLUDED.daily_budget_usd,
			    monthly_budget_usd   = EXCLUDED.monthly_budget_usd,
			    max_cost_per_ticket  = EXCLUDED.max_cost_per_ticket,
			    pause_on_exceeded    = EXCLUDED.pause_on_exceeded,
			    updated_at           = now()
		RETURNING
			tenant_id, daily_budget_usd, monthly_budget_usd,
			max_cost_per_ticket, pause_on_exceeded, updated_at
	`
	var (
		b                                   TenantBudget
		dailyLimit, monthlyLimit, perTicket pgtype.Numeric
	)
	err := db.QueryRow(ctx, q,
		p.TenantID,
		floatPtrToNumericArg(p.DailyBudgetUSD),
		floatPtrToNumericArg(p.MonthlyBudgetUSD),
		floatPtrToNumericArg(p.MaxCostPerTicket),
		p.PauseOnExceeded,
	).Scan(
		&b.TenantID,
		&dailyLimit, &monthlyLimit, &perTicket,
		&b.PauseOnExceeded,
		&b.UpdatedAt,
	)
	if err != nil {
		return TenantBudget{}, err
	}
	b.DailyBudgetUSD = numericToFloatPtr(dailyLimit)
	b.MonthlyBudgetUSD = numericToFloatPtr(monthlyLimit)
	b.MaxCostPerTicket = numericToFloatPtr(perTicket)
	return b, nil
}

// floatPtrToNumericArg converts *float64 → pgx arg. nil maps to a SQL NULL by
// returning a nil interface; a concrete value is passed through as float64
// (pgx encodes that into NUMERIC).
func floatPtrToNumericArg(f *float64) any {
	if f == nil {
		return nil
	}
	return *f
}

func numericToFloatPtr(n pgtype.Numeric) *float64 {
	if !n.Valid {
		return nil
	}
	v, err := n.Float64Value()
	if err != nil || !v.Valid {
		return nil
	}
	out := v.Float64
	return &out
}
