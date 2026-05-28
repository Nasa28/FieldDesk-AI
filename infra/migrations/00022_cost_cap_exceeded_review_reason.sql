-- +goose Up
-- +goose StatementBegin

-- Slice 2 of PRD §12: allow 'cost_cap_exceeded' as a human_reviews reason
-- so per-ticket max_cost_per_ticket pre-flight blocks route to the same
-- review queue every other AI failure goes through. Daily/monthly already
-- has 'budget_exceeded' (migration 00016); this is the per-ticket sibling.
ALTER TABLE human_reviews DROP CONSTRAINT IF EXISTS human_reviews_reason_check;
ALTER TABLE human_reviews
    ADD CONSTRAINT human_reviews_reason_check
    CHECK (reason IN ('low_confidence', 'invalid_json',
                      'missing_fields', 'unclear_audio',
                      'provider_uncertainty', 'sensitive',
                      'fallback', 'budget_exceeded',
                      'cost_cap_exceeded', 'other'));

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin

ALTER TABLE human_reviews DROP CONSTRAINT IF EXISTS human_reviews_reason_check;
ALTER TABLE human_reviews
    ADD CONSTRAINT human_reviews_reason_check
    CHECK (reason IN ('low_confidence', 'invalid_json',
                      'missing_fields', 'unclear_audio',
                      'provider_uncertainty', 'sensitive',
                      'fallback', 'budget_exceeded', 'other'));

-- +goose StatementEnd
