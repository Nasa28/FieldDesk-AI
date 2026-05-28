-- +goose Up
-- +goose StatementBegin
UPDATE voice_notes
SET status = 'failed',
    error_class = COALESCE(error_class, 'transcription_failed'),
    updated_at = now()
WHERE status = 'failed_transcription';

ALTER TABLE voice_notes DROP CONSTRAINT voice_notes_status_check;
ALTER TABLE voice_notes
    ADD CONSTRAINT voice_notes_status_check
    CHECK (status IN ('pending_upload', 'uploaded', 'transcribing',
                      'transcribed', 'failed'));
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
ALTER TABLE voice_notes DROP CONSTRAINT voice_notes_status_check;
ALTER TABLE voice_notes
    ADD CONSTRAINT voice_notes_status_check
    CHECK (status IN ('pending_upload', 'uploaded', 'transcribing',
                      'transcribed', 'failed', 'failed_transcription'));
-- +goose StatementEnd
