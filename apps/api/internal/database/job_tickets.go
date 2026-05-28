package database

import (
	"context"
	"errors"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

var ErrInvalidCorrection = errors.New("invalid correction")

const jobTicketColumns = `
	id, tenant_id, voice_note_id, transcript_id, status, source,
	customer_name, customer_phone, service_address,
	trade_type, issue_summary, detailed_description,
	priority, preferred_visit_time,
	required_skills, suggested_parts, safety_concerns,
	warranty_mention, follow_up_questions,
	confidence, human_review_required,
	approved_by, approved_at, rejected_reason, rejected_at,
	created_at, updated_at
`

func scanJobTicket(row pgx.Row, t *JobTicket) error {
	return row.Scan(
		&t.ID, &t.TenantID, &t.VoiceNoteID, &t.TranscriptID, &t.Status, &t.Source,
		&t.CustomerName, &t.CustomerPhone, &t.ServiceAddress,
		&t.TradeType, &t.IssueSummary, &t.DetailedDescription,
		&t.Priority, &t.PreferredVisitTime,
		&t.RequiredSkills, &t.SuggestedParts, &t.SafetyConcerns,
		&t.WarrantyMention, &t.FollowUpQuestions,
		&t.Confidence, &t.HumanReviewRequired,
		&t.ApprovedBy, &t.ApprovedAt, &t.RejectedReason, &t.RejectedAt,
		&t.CreatedAt, &t.UpdatedAt,
	)
}

// TicketCorrection mirrors the correction payload reviewers send. Scalar fields
// are optional. Slice fields use pointers so omitted arrays preserve existing
// values on update, while explicit [] clears the column.
type TicketCorrection struct {
	CustomerName        *string   `json:"customer_name,omitempty"`
	CustomerPhone       *string   `json:"customer_phone,omitempty"`
	ServiceAddress      *string   `json:"service_address,omitempty"`
	TradeType           *string   `json:"trade_type,omitempty"`
	IssueSummary        *string   `json:"issue_summary,omitempty"`
	DetailedDescription *string   `json:"detailed_description,omitempty"`
	Priority            *string   `json:"priority,omitempty"`
	PreferredVisitTime  *string   `json:"preferred_visit_time,omitempty"`
	RequiredSkills      *[]string `json:"required_skills,omitempty"`
	SuggestedParts      *[]string `json:"suggested_parts,omitempty"`
	SafetyConcerns      *[]string `json:"safety_concerns,omitempty"`
	WarrantyMentioned   *bool     `json:"warranty_mentioned,omitempty"`
	FollowUpQuestions   *[]string `json:"follow_up_questions,omitempty"`
}

func (c TicketCorrection) HasPatchField() bool {
	if c.WarrantyMentioned != nil ||
		c.RequiredSkills != nil ||
		c.SuggestedParts != nil ||
		c.SafetyConcerns != nil ||
		c.FollowUpQuestions != nil {
		return true
	}
	return hasNonEmptyStringField(c)
}

func (c TicketCorrection) HasTicketSeedField() bool {
	return hasNonEmptyStringField(c) ||
		nonEmptyStringSlicePtr(c.RequiredSkills) ||
		nonEmptyStringSlicePtr(c.SuggestedParts) ||
		nonEmptyStringSlicePtr(c.SafetyConcerns) ||
		nonEmptyStringSlicePtr(c.FollowUpQuestions)
}

func hasNonEmptyStringField(c TicketCorrection) bool {
	return nonEmptyStringPtr(c.CustomerName) ||
		nonEmptyStringPtr(c.CustomerPhone) ||
		nonEmptyStringPtr(c.ServiceAddress) ||
		nonEmptyStringPtr(c.TradeType) ||
		nonEmptyStringPtr(c.IssueSummary) ||
		nonEmptyStringPtr(c.DetailedDescription) ||
		nonEmptyStringPtr(c.Priority) ||
		nonEmptyStringPtr(c.PreferredVisitTime)
}

func nonEmptyStringPtr(s *string) bool {
	return s != nil && strings.TrimSpace(*s) != ""
}

func nonEmptyStringSlicePtr(s *[]string) bool {
	if s == nil {
		return false
	}
	for _, v := range *s {
		if strings.TrimSpace(v) != "" {
			return true
		}
	}
	return false
}

func stringSliceOrEmpty(s *[]string) []string {
	if s == nil {
		return []string{}
	}
	return *s
}

func stringSliceArg(s *[]string) any {
	if s == nil {
		return nil
	}
	return *s
}

func GetTicket(ctx context.Context, db *DB, id, tenantID uuid.UUID) (JobTicket, error) {
	q := "SELECT " + jobTicketColumns + " FROM job_tickets WHERE id = $1 AND tenant_id = $2"
	var t JobTicket
	err := scanJobTicket(db.QueryRow(ctx, q, id, tenantID), &t)
	if errors.Is(err, pgx.ErrNoRows) {
		return JobTicket{}, ErrNotFound
	}
	return t, err
}

func ticketMissingOrInvalidState(ctx context.Context, db *DB, id, tenantID uuid.UUID) error {
	var exists bool
	q := `SELECT EXISTS (
		SELECT 1 FROM job_tickets WHERE id = $1 AND tenant_id = $2
	)`
	if err := db.QueryRow(ctx, q, id, tenantID).Scan(&exists); err != nil {
		return err
	}
	if !exists {
		return ErrNotFound
	}
	return ErrInvalidState
}

func ticketMissingOrInvalidStateTx(ctx context.Context, tx pgx.Tx, id, tenantID uuid.UUID) error {
	var exists bool
	q := `SELECT EXISTS (
		SELECT 1 FROM job_tickets WHERE id = $1 AND tenant_id = $2
	)`
	if err := tx.QueryRow(ctx, q, id, tenantID).Scan(&exists); err != nil {
		return err
	}
	if !exists {
		return ErrNotFound
	}
	return ErrInvalidState
}

type ListTicketsParams struct {
	TenantID uuid.UUID
	Status   string
	Limit    int32
	Offset   int32
}

func ListTickets(ctx context.Context, db *DB, p ListTicketsParams) ([]JobTicket, error) {
	limit := p.Limit
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	q := "SELECT " + jobTicketColumns + ` FROM job_tickets
		WHERE tenant_id = $1
		  AND ($2::text = '' OR status = $2)
		ORDER BY created_at DESC
		LIMIT $3 OFFSET $4`
	rows, err := db.Query(ctx, q, p.TenantID, p.Status, limit, p.Offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]JobTicket, 0)
	for rows.Next() {
		var t JobTicket
		if err := scanJobTicket(rows, &t); err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, rows.Err()
}

func ApproveTicket(
	ctx context.Context, db *DB, id, tenantID uuid.UUID, approvedBy *uuid.UUID,
) (JobTicket, error) {
	q := `UPDATE job_tickets
			SET status = 'approved',
			    approved_at = now(),
			    approved_by = $3,
			    rejected_at = NULL,
			    rejected_reason = NULL,
			    updated_at = now()
			WHERE id = $1 AND tenant_id = $2
			  AND status = 'draft'
			RETURNING ` + jobTicketColumns
	var t JobTicket
	err := scanJobTicket(db.QueryRow(ctx, q, id, tenantID, approvedBy), &t)
	if errors.Is(err, pgx.ErrNoRows) {
		return JobTicket{}, ticketMissingOrInvalidState(ctx, db, id, tenantID)
	}
	return t, err
}

func RejectTicket(
	ctx context.Context, db *DB, id, tenantID uuid.UUID, reason string,
) (JobTicket, error) {
	q := `UPDATE job_tickets
			SET status = 'rejected',
			    rejected_at = now(),
			    rejected_reason = NULLIF($3, ''),
			    approved_at = NULL,
			    approved_by = NULL,
			    updated_at = now()
			WHERE id = $1 AND tenant_id = $2
			  AND status IN ('draft', 'needs_review')
			RETURNING ` + jobTicketColumns
	var t JobTicket
	err := scanJobTicket(db.QueryRow(ctx, q, id, tenantID, reason), &t)
	if errors.Is(err, pgx.ErrNoRows) {
		return JobTicket{}, ticketMissingOrInvalidState(ctx, db, id, tenantID)
	}
	return t, err
}

func UpdateTicket(ctx context.Context, db *DB, id, tenantID uuid.UUID, c TicketCorrection) (JobTicket, error) {
	q := `UPDATE job_tickets SET
			customer_name = COALESCE($3, customer_name),
			customer_phone = COALESCE($4, customer_phone),
			service_address = COALESCE($5, service_address),
			trade_type = COALESCE($6, trade_type),
			issue_summary = COALESCE($7, issue_summary),
			detailed_description = COALESCE($8, detailed_description),
			priority = COALESCE($9, priority),
			preferred_visit_time = COALESCE($10, preferred_visit_time),
			required_skills = COALESCE($11::text[], required_skills),
			suggested_parts = COALESCE($12::text[], suggested_parts),
			safety_concerns = COALESCE($13::text[], safety_concerns),
			warranty_mention = COALESCE($14, warranty_mention),
			follow_up_questions = COALESCE($15::text[], follow_up_questions),
			status = 'draft',
			human_review_required = false,
			approved_at = NULL,
			approved_by = NULL,
			rejected_at = NULL,
			rejected_reason = NULL,
			updated_at = now()
		WHERE id = $1 AND tenant_id = $2
		  AND status IN ('draft', 'needs_review', 'rejected')
		RETURNING ` + jobTicketColumns
	var t JobTicket
	err := scanJobTicket(db.QueryRow(ctx, q, id, tenantID,
		c.CustomerName, c.CustomerPhone, c.ServiceAddress,
		c.TradeType, c.IssueSummary, c.DetailedDescription,
		c.Priority, c.PreferredVisitTime,
		stringSliceArg(c.RequiredSkills),
		stringSliceArg(c.SuggestedParts),
		stringSliceArg(c.SafetyConcerns),
		c.WarrantyMentioned,
		stringSliceArg(c.FollowUpQuestions),
	), &t)
	if errors.Is(err, pgx.ErrNoRows) {
		return JobTicket{}, ticketMissingOrInvalidState(ctx, db, id, tenantID)
	}
	return t, err
}

// createOrUpdateTicketTx runs inside an existing pgx.Tx so the review-resolve
// flow can keep ticket and review in a single atomic transaction.
func createOrUpdateTicketTx(
	ctx context.Context,
	tx pgx.Tx,
	tenantID uuid.UUID,
	existingID *uuid.UUID,
	voiceNoteID, transcriptID *uuid.UUID,
	c TicketCorrection,
) (JobTicket, error) {
	if existingID != nil {
		q := `UPDATE job_tickets SET
			customer_name = COALESCE($3, customer_name),
			customer_phone = COALESCE($4, customer_phone),
			service_address = COALESCE($5, service_address),
			trade_type = COALESCE($6, trade_type),
			issue_summary = COALESCE($7, issue_summary),
			detailed_description = COALESCE($8, detailed_description),
			priority = COALESCE($9, priority),
			preferred_visit_time = COALESCE($10, preferred_visit_time),
			required_skills = COALESCE($11::text[], required_skills),
			suggested_parts = COALESCE($12::text[], suggested_parts),
			safety_concerns = COALESCE($13::text[], safety_concerns),
			warranty_mention = COALESCE($14, warranty_mention),
			follow_up_questions = COALESCE($15::text[], follow_up_questions),
			status = 'draft',
			human_review_required = false,
			approved_at = NULL,
			approved_by = NULL,
			rejected_at = NULL,
			rejected_reason = NULL,
			updated_at = now()
		WHERE id = $1 AND tenant_id = $2
		  AND status IN ('draft', 'needs_review')
		RETURNING ` + jobTicketColumns
		var t JobTicket
		err := scanJobTicket(tx.QueryRow(ctx, q, *existingID, tenantID,
			c.CustomerName, c.CustomerPhone, c.ServiceAddress,
			c.TradeType, c.IssueSummary, c.DetailedDescription,
			c.Priority, c.PreferredVisitTime,
			stringSliceArg(c.RequiredSkills),
			stringSliceArg(c.SuggestedParts),
			stringSliceArg(c.SafetyConcerns),
			c.WarrantyMentioned,
			stringSliceArg(c.FollowUpQuestions),
		), &t)
		if errors.Is(err, pgx.ErrNoRows) {
			return JobTicket{}, ticketMissingOrInvalidStateTx(ctx, tx, *existingID, tenantID)
		}
		return t, err
	}

	q := `INSERT INTO job_tickets (
		tenant_id, voice_note_id, transcript_id,
		customer_name, customer_phone, service_address,
		trade_type, issue_summary, detailed_description,
		priority, preferred_visit_time,
		required_skills, suggested_parts, safety_concerns,
		warranty_mention, follow_up_questions,
		status, source, human_review_required
	) VALUES (
		$1, $2, $3,
		$4, $5, $6,
		$7, $8, $9,
		$10, $11,
		$12, $13, $14,
		$15, $16,
		'draft', 'ai_extraction', false
	) RETURNING ` + jobTicketColumns
	var t JobTicket
	err := scanJobTicket(tx.QueryRow(ctx, q,
		tenantID, voiceNoteID, transcriptID,
		c.CustomerName, c.CustomerPhone, c.ServiceAddress,
		c.TradeType, c.IssueSummary, c.DetailedDescription,
		c.Priority, c.PreferredVisitTime,
		stringSliceOrEmpty(c.RequiredSkills),
		stringSliceOrEmpty(c.SuggestedParts),
		stringSliceOrEmpty(c.SafetyConcerns),
		c.WarrantyMentioned,
		stringSliceOrEmpty(c.FollowUpQuestions),
	), &t)
	return t, err
}
