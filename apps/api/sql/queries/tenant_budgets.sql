-- name: GetTenantBudgetUsage :one
-- Reads from the v_tenant_budget_usage view defined in migration 00016.
-- The view returns a row even when no budget is configured (NULL limits).
SELECT
    tenant_id,
    daily_budget_usd,
    monthly_budget_usd,
    max_cost_per_ticket,
    pause_on_exceeded,
    daily_spend_usd,
    monthly_spend_usd,
    daily_over,
    monthly_over
FROM v_tenant_budget_usage
WHERE tenant_id = $1;

-- name: UpsertTenantBudget :one
-- A tenant has at most one budget row. NULL columns mean "no cap."
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
    max_cost_per_ticket, pause_on_exceeded, updated_at;
