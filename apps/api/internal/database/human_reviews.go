package database

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

const humanReviewColumns = `
	id, tenant_id, job_ticket_id, ai_job_id,
	voice_note_id, transcript_id, ai_extraction_id,
	reason, status, reviewer_id, correction, notes,
	created_at, resolved_at
`

func scanHumanReview(row pgx.Row, h *HumanReview) error {
	var correction []byte
	err := row.Scan(
		&h.ID, &h.TenantID, &h.JobTicketID, &h.AIJobID,
		&h.VoiceNoteID, &h.TranscriptID, &h.AIExtractionID,
		&h.Reason, &h.Status, &h.ReviewerID, &correction, &h.Notes,
		&h.CreatedAt, &h.ResolvedAt,
	)
	if err != nil {
		return err
	}
	h.Correction = json.RawMessage(correction)
	return nil
}

// ReviewQueueItem is the enriched list row returned by GET /v1/review-queue.
// Each *Summary field may be nil if the FK is unset or the linked row is gone.
type ReviewQueueItem struct {
	Review      HumanReview        `json:"review"`
	VoiceNote   *VoiceNoteSummary  `json:"voice_note,omitempty"`
	Transcript  *TranscriptSummary `json:"transcript,omitempty"`
	Extraction  *ExtractionSummary `json:"extraction,omitempty"`
	DraftTicket *TicketSummary     `json:"draft_ticket,omitempty"`
}

type VoiceNoteSummary struct {
	ID        uuid.UUID `json:"id"`
	Status    string    `json:"status"`
	MimeType  string    `json:"mime_type"`
	CreatedAt time.Time `json:"created_at"`
}

type TranscriptSummary struct {
	ID       uuid.UUID `json:"id"`
	Language *string   `json:"language,omitempty"`
	Preview  string    `json:"preview"`
}

type ExtractionSummary struct {
	ID           uuid.UUID       `json:"id"`
	JSONValid    bool            `json:"json_valid"`
	Confidence   *float64        `json:"confidence,omitempty"`
	ParsedOutput json.RawMessage `json:"parsed_output,omitempty"`
	ErrorMessage *string         `json:"error_message,omitempty"`
	Provider     string          `json:"provider"`
	Model        string          `json:"model"`
}

type TicketSummary struct {
	ID           uuid.UUID `json:"id"`
	Status       string    `json:"status"`
	Source       string    `json:"source"`
	CustomerName *string   `json:"customer_name,omitempty"`
	IssueSummary *string   `json:"issue_summary,omitempty"`
}

type ListReviewsParams struct {
	TenantID uuid.UUID
	Status   string
	Reason   string
	Limit    int32
	Offset   int32
}

func ListOpenHumanReviews(ctx context.Context, db *DB, p ListReviewsParams) ([]ReviewQueueItem, error) {
	status := p.Status
	if status == "" {
		status = "open"
	}
	limit := p.Limit
	if limit <= 0 || limit > 200 {
		limit = 50
	}

	q := `
		SELECT
			hr.id, hr.tenant_id, hr.job_ticket_id, hr.ai_job_id,
			hr.voice_note_id, hr.transcript_id, hr.ai_extraction_id,
			hr.reason, hr.status, hr.reviewer_id, hr.correction, hr.notes,
			hr.created_at, hr.resolved_at,
			vn.id, vn.status, vn.mime_type, vn.created_at,
			t.id, t.language, LEFT(COALESCE(t.text, ''), 280),
			e.id, e.json_valid, e.confidence, e.parsed_output, e.error_message, e.provider, e.model,
			tk.id, tk.status, tk.source, tk.customer_name, tk.issue_summary
		FROM human_reviews hr
		LEFT JOIN voice_notes    vn ON vn.id = hr.voice_note_id    AND vn.tenant_id = hr.tenant_id
		LEFT JOIN transcripts    t  ON t.id  = hr.transcript_id    AND t.tenant_id  = hr.tenant_id
		LEFT JOIN ai_extractions e  ON e.id  = hr.ai_extraction_id AND e.tenant_id  = hr.tenant_id
		LEFT JOIN job_tickets    tk ON tk.id = hr.job_ticket_id    AND tk.tenant_id = hr.tenant_id
		WHERE hr.tenant_id = $1
		  AND hr.status = $2
		  AND ($3::text = '' OR hr.reason = $3)
		ORDER BY hr.created_at DESC
		LIMIT $4 OFFSET $5
	`
	rows, err := db.Query(ctx, q, p.TenantID, status, p.Reason, limit, p.Offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]ReviewQueueItem, 0)
	for rows.Next() {
		var (
			item    ReviewQueueItem
			hrCorr  []byte
			vnID    *uuid.UUID
			vnStat  *string
			vnMime  *string
			vnAt    *time.Time
			tID     *uuid.UUID
			tLang   *string
			tPrev   *string
			eID     *uuid.UUID
			eValid  *bool
			eConf   *float64
			eParsed []byte
			eErr    *string
			eProv   *string
			eModel  *string
			tkID    *uuid.UUID
			tkStat  *string
			tkSrc   *string
			tkCust  *string
			tkSum   *string
		)
		if err := rows.Scan(
			&item.Review.ID, &item.Review.TenantID, &item.Review.JobTicketID, &item.Review.AIJobID,
			&item.Review.VoiceNoteID, &item.Review.TranscriptID, &item.Review.AIExtractionID,
			&item.Review.Reason, &item.Review.Status, &item.Review.ReviewerID,
			&hrCorr, &item.Review.Notes,
			&item.Review.CreatedAt, &item.Review.ResolvedAt,
			&vnID, &vnStat, &vnMime, &vnAt,
			&tID, &tLang, &tPrev,
			&eID, &eValid, &eConf, &eParsed, &eErr, &eProv, &eModel,
			&tkID, &tkStat, &tkSrc, &tkCust, &tkSum,
		); err != nil {
			return nil, err
		}
		item.Review.Correction = json.RawMessage(hrCorr)

		if vnID != nil {
			item.VoiceNote = &VoiceNoteSummary{
				ID: *vnID, Status: deref(vnStat), MimeType: deref(vnMime), CreatedAt: derefTime(vnAt),
			}
		}
		if tID != nil {
			item.Transcript = &TranscriptSummary{ID: *tID, Language: tLang, Preview: deref(tPrev)}
		}
		if eID != nil {
			item.Extraction = &ExtractionSummary{
				ID:           *eID,
				JSONValid:    derefBool(eValid),
				Confidence:   eConf,
				ParsedOutput: json.RawMessage(eParsed),
				ErrorMessage: eErr,
				Provider:     deref(eProv),
				Model:        deref(eModel),
			}
		}
		if tkID != nil {
			item.DraftTicket = &TicketSummary{
				ID: *tkID, Status: deref(tkStat), Source: deref(tkSrc),
				CustomerName: tkCust, IssueSummary: tkSum,
			}
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func GetHumanReview(ctx context.Context, db *DB, id, tenantID uuid.UUID) (HumanReview, error) {
	q := "SELECT " + humanReviewColumns + " FROM human_reviews WHERE id = $1 AND tenant_id = $2"
	var h HumanReview
	err := scanHumanReview(db.QueryRow(ctx, q, id, tenantID), &h)
	if errors.Is(err, pgx.ErrNoRows) {
		return HumanReview{}, ErrNotFound
	}
	return h, err
}

type ResolveHumanReviewParams struct {
	ReviewID   uuid.UUID
	TenantID   uuid.UUID
	ReviewerID *uuid.UUID
	Correction TicketCorrection
	Notes      *string
}

type ResolveHumanReviewResult struct {
	Review HumanReview `json:"review"`
	Ticket JobTicket   `json:"ticket"`
}

// ResolveHumanReview locks the review row, either updates the existing
// draft ticket or creates a fresh one from the correction, then marks the
// review resolved. All three writes happen in a single transaction so a
// reviewer never sees a half-resolved state.
func ResolveHumanReview(
	ctx context.Context, db *DB, p ResolveHumanReviewParams,
) (ResolveHumanReviewResult, error) {
	tx, err := db.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return ResolveHumanReviewResult{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	const lockReview = `
		SELECT ` + humanReviewColumns + `
		FROM human_reviews
		WHERE id = $1 AND tenant_id = $2
		FOR UPDATE
	`
	var review HumanReview
	err = scanHumanReview(tx.QueryRow(ctx, lockReview, p.ReviewID, p.TenantID), &review)
	if errors.Is(err, pgx.ErrNoRows) {
		return ResolveHumanReviewResult{}, ErrNotFound
	}
	if err != nil {
		return ResolveHumanReviewResult{}, err
	}
	if review.Status != "open" {
		return ResolveHumanReviewResult{}, ErrInvalidState
	}
	if review.JobTicketID == nil {
		if !p.Correction.HasTicketSeedField() {
			return ResolveHumanReviewResult{}, ErrInvalidCorrection
		}
	} else if !p.Correction.HasPatchField() {
		return ResolveHumanReviewResult{}, ErrInvalidCorrection
	}

	ticket, err := createOrUpdateTicketTx(
		ctx, tx, p.TenantID,
		review.JobTicketID,
		review.VoiceNoteID, review.TranscriptID,
		p.Correction,
	)
	if err != nil {
		return ResolveHumanReviewResult{}, err
	}

	correctionJSON, err := json.Marshal(p.Correction)
	if err != nil {
		return ResolveHumanReviewResult{}, err
	}

	const updateReview = `
		UPDATE human_reviews
		SET status = 'resolved',
		    resolved_at = now(),
		    job_ticket_id = $3,
		    correction = $4,
		    notes = COALESCE($5, notes),
		    reviewer_id = COALESCE($6, reviewer_id)
		WHERE id = $1 AND tenant_id = $2
		RETURNING ` + humanReviewColumns
	if err := scanHumanReview(tx.QueryRow(ctx, updateReview,
		p.ReviewID, p.TenantID, ticket.ID, correctionJSON, p.Notes, p.ReviewerID,
	), &review); err != nil {
		return ResolveHumanReviewResult{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return ResolveHumanReviewResult{}, err
	}
	return ResolveHumanReviewResult{Review: review, Ticket: ticket}, nil
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

func derefBool(b *bool) bool {
	if b == nil {
		return false
	}
	return *b
}

func derefTime(t *time.Time) time.Time {
	if t == nil {
		return time.Time{}
	}
	return *t
}
