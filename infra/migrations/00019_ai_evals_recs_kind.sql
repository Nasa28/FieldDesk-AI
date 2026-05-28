-- +goose Up
-- +goose StatementBegin

-- Phase 4.5 added a new LLM call (draft_ticket → recommendations) with its
-- own injection-eval surface. Extend the CHECK on ai_eval_runs.kind so the
-- runner can persist a row tagged 'recs' instead of bucketing it under
-- 'extraction', which would conflate two distinct prompts in the dashboard.
-- ai_eval_cases gets the same extension so a future seeded-case workflow
-- can store cases server-side.

ALTER TABLE ai_eval_runs
    DROP CONSTRAINT IF EXISTS ai_eval_runs_kind_check;
ALTER TABLE ai_eval_runs
    ADD CONSTRAINT ai_eval_runs_kind_check
    CHECK (kind IN ('extraction', 'rag', 'transcription', 'recs'));

ALTER TABLE ai_eval_cases
    DROP CONSTRAINT IF EXISTS ai_eval_cases_kind_check;
ALTER TABLE ai_eval_cases
    ADD CONSTRAINT ai_eval_cases_kind_check
    CHECK (kind IN ('extraction', 'rag', 'transcription', 'recs'));

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin

ALTER TABLE ai_eval_runs
    DROP CONSTRAINT IF EXISTS ai_eval_runs_kind_check;
ALTER TABLE ai_eval_runs
    ADD CONSTRAINT ai_eval_runs_kind_check
    CHECK (kind IN ('extraction', 'rag', 'transcription'));

ALTER TABLE ai_eval_cases
    DROP CONSTRAINT IF EXISTS ai_eval_cases_kind_check;
ALTER TABLE ai_eval_cases
    ADD CONSTRAINT ai_eval_cases_kind_check
    CHECK (kind IN ('extraction', 'rag', 'transcription'));

-- +goose StatementEnd
