-- +goose Up
-- +goose StatementBegin

-- Allow 'budget_exceeded' as a human_reviews reason so pre-flight budget blocks
-- can route to the same review queue every other AI failure goes through.
ALTER TABLE human_reviews DROP CONSTRAINT IF EXISTS human_reviews_reason_check;
ALTER TABLE human_reviews
    ADD CONSTRAINT human_reviews_reason_check
    CHECK (reason IN ('low_confidence', 'invalid_json',
                      'missing_fields', 'unclear_audio',
                      'provider_uncertainty', 'sensitive',
                      'fallback', 'budget_exceeded', 'other'));

-- Single source of truth for "is this tenant over budget right now?". Both the
-- Go API admin view and the Python worker's pre-flight check read from this
-- view so the math can't drift. Spend buckets use UTC day / first-of-UTC-month
-- to match how budgets are typically reasoned about (daily/monthly cap).
--
-- NULL limit means "no cap configured" → over flags are false.
-- Failed provider calls still cost money → SUM(cost_usd) is unconditional.
CREATE OR REPLACE VIEW v_tenant_budget_usage AS
SELECT
    t.id                                                   AS tenant_id,
    b.daily_budget_usd,
    b.monthly_budget_usd,
    b.max_cost_per_ticket,
    COALESCE(b.pause_on_exceeded, true)                    AS pause_on_exceeded,
    COALESCE(daily.spend, 0)::numeric(14, 6)               AS daily_spend_usd,
    COALESCE(monthly.spend, 0)::numeric(14, 6)             AS monthly_spend_usd,
    CASE
        WHEN b.daily_budget_usd IS NULL THEN false
        ELSE COALESCE(daily.spend, 0) >= b.daily_budget_usd
    END                                                    AS daily_over,
    CASE
        WHEN b.monthly_budget_usd IS NULL THEN false
        ELSE COALESCE(monthly.spend, 0) >= b.monthly_budget_usd
    END                                                    AS monthly_over
FROM tenants t
LEFT JOIN tenant_ai_budgets b ON b.tenant_id = t.id
LEFT JOIN LATERAL (
    SELECT SUM(cost_usd) AS spend
    FROM ai_model_calls
    WHERE tenant_id = t.id
      AND created_at >= (date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
) daily ON true
LEFT JOIN LATERAL (
    SELECT SUM(cost_usd) AS spend
    FROM ai_model_calls
    WHERE tenant_id = t.id
      AND created_at >= (date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
) monthly ON true;

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP VIEW IF EXISTS v_tenant_budget_usage;

ALTER TABLE human_reviews DROP CONSTRAINT IF EXISTS human_reviews_reason_check;
ALTER TABLE human_reviews
    ADD CONSTRAINT human_reviews_reason_check
    CHECK (reason IN ('low_confidence', 'invalid_json',
                      'missing_fields', 'unclear_audio',
                      'provider_uncertainty', 'sensitive',
                      'fallback', 'other'));
-- +goose StatementEnd
