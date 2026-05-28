-- +goose Up
-- +goose StatementBegin
ALTER TABLE ai_jobs
    ADD COLUMN locked_by TEXT,
    ADD COLUMN lease_expires_at TIMESTAMPTZ;

CREATE INDEX ai_jobs_processing_lease_idx
    ON ai_jobs(lease_expires_at)
    WHERE status = 'processing';
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP INDEX IF EXISTS ai_jobs_processing_lease_idx;

ALTER TABLE ai_jobs
    DROP COLUMN lease_expires_at,
    DROP COLUMN locked_by;
-- +goose StatementEnd
