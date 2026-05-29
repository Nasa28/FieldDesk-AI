-- +goose Up
-- +goose StatementBegin
CREATE TABLE voice_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,
    mode            TEXT NOT NULL CHECK (mode IN ('qa', 'intake')),
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at    TIMESTAMPTZ
);

CREATE INDEX voice_sessions_tenant_id_idx ON voice_sessions(tenant_id);
CREATE INDEX voice_sessions_token_live_idx
    ON voice_sessions(token_hash)
    WHERE consumed_at IS NULL;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS voice_sessions;
-- +goose StatementEnd
