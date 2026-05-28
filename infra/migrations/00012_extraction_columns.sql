-- +goose Up
-- +goose StatementBegin
ALTER TABLE ai_extractions ADD COLUMN error_message TEXT;

ALTER TABLE ai_model_calls
    ADD COLUMN response_meta JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE job_tickets
    ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'
        CHECK (source IN ('manual', 'ai_extraction'));

ALTER TABLE human_reviews DROP CONSTRAINT human_reviews_reason_check;
ALTER TABLE human_reviews
    ADD CONSTRAINT human_reviews_reason_check
    CHECK (reason IN ('low_confidence', 'invalid_json', 'missing_fields',
                      'provider_uncertainty', 'unclear_audio', 'sensitive',
                      'fallback', 'other'));
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
ALTER TABLE human_reviews DROP CONSTRAINT human_reviews_reason_check;
ALTER TABLE human_reviews
    ADD CONSTRAINT human_reviews_reason_check
    CHECK (reason IN ('low_confidence', 'invalid_json', 'missing_fields',
                      'unclear_audio', 'sensitive', 'fallback', 'other'));

ALTER TABLE job_tickets DROP COLUMN source;
ALTER TABLE ai_model_calls DROP COLUMN response_meta;
ALTER TABLE ai_extractions DROP COLUMN error_message;
-- +goose StatementEnd
