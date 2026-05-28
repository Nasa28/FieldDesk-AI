-- +goose Up
-- +goose StatementBegin
CREATE TABLE ai_eval_cases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN ('extraction', 'rag', 'transcription')),
    name            TEXT NOT NULL,
    input           JSONB NOT NULL,
    expected        JSONB NOT NULL,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ai_eval_cases_kind_idx ON ai_eval_cases(kind);

CREATE TABLE ai_eval_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN ('extraction', 'rag', 'transcription')),
    prompt_version  TEXT NOT NULL,
    model           TEXT NOT NULL,
    total_cases     INTEGER NOT NULL DEFAULT 0,
    passed          INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    metrics         JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

CREATE INDEX ai_eval_runs_kind_started_at_idx ON ai_eval_runs(kind, started_at DESC);

CREATE TABLE tenant_ai_budgets (
    tenant_id           UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    daily_budget_usd    NUMERIC(12, 2),
    monthly_budget_usd  NUMERIC(12, 2),
    max_cost_per_ticket NUMERIC(12, 4),
    pause_on_exceeded   BOOLEAN NOT NULL DEFAULT true,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS tenant_ai_budgets;
DROP TABLE IF EXISTS ai_eval_runs;
DROP TABLE IF EXISTS ai_eval_cases;
-- +goose StatementEnd
