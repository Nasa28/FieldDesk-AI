-- +goose Up
-- +goose StatementBegin
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP EXTENSION IF EXISTS "vector";
DROP EXTENSION IF EXISTS "pgcrypto";
-- +goose StatementEnd
