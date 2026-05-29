package database

import (
	"context"

	"github.com/google/uuid"
)

// InsertTranscriptParams creates a transcript row directly (no audio upload /
// transcribe step). Used by voice intake, where the live conversation already
// produced text that the existing extract job can turn into a draft ticket.
type InsertTranscriptParams struct {
	TenantID    uuid.UUID
	VoiceNoteID uuid.UUID
	Text        string
	Provider    string
	Model       string
}

func InsertTranscript(ctx context.Context, db *DB, p InsertTranscriptParams) (uuid.UUID, error) {
	const q = `
		INSERT INTO transcripts (tenant_id, voice_note_id, text, provider, model)
		VALUES ($1, $2, $3, $4, $5)
		RETURNING id
	`
	var id uuid.UUID
	err := db.QueryRow(ctx, q, p.TenantID, p.VoiceNoteID, p.Text, p.Provider, p.Model).Scan(&id)
	return id, err
}
