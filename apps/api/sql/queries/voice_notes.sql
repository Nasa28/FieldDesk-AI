-- name: CreateVoiceNote :one
INSERT INTO voice_notes (id, tenant_id, uploaded_by, object_key, mime_type, size_bytes, status)
VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING *;

-- name: GetVoiceNote :one
SELECT * FROM voice_notes
WHERE id = $1 AND tenant_id = $2;

-- name: ListVoiceNotes :many
SELECT * FROM voice_notes
WHERE tenant_id = $1
ORDER BY created_at DESC
LIMIT $2;

-- name: UpdateVoiceNoteStatus :exec
UPDATE voice_notes
SET status = $1, updated_at = now()
WHERE id = $2 AND tenant_id = $3;
