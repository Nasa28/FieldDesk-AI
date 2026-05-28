-- +goose Up
-- +goose StatementBegin
ALTER TABLE voice_notes DROP CONSTRAINT voice_notes_status_check;
ALTER TABLE voice_notes
    ADD CONSTRAINT voice_notes_status_check
    CHECK (status IN ('pending_upload', 'uploaded', 'transcribing', 'transcribed', 'failed'));
ALTER TABLE voice_notes ALTER COLUMN status SET DEFAULT 'pending_upload';
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
ALTER TABLE voice_notes ALTER COLUMN status SET DEFAULT 'uploaded';
ALTER TABLE voice_notes DROP CONSTRAINT voice_notes_status_check;
ALTER TABLE voice_notes
    ADD CONSTRAINT voice_notes_status_check
    CHECK (status IN ('uploaded', 'transcribing', 'transcribed', 'failed'));
-- +goose StatementEnd
