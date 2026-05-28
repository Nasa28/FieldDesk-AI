package database

import (
	"encoding/json"
	"time"

	"github.com/google/uuid"
)

type VoiceNote struct {
	ID         uuid.UUID  `json:"id"`
	TenantID   uuid.UUID  `json:"tenant_id"`
	UploadedBy *uuid.UUID `json:"uploaded_by,omitempty"`
	ObjectKey  string     `json:"object_key"`
	MimeType   string     `json:"mime_type"`
	DurationMS *int32     `json:"duration_ms,omitempty"`
	SizeBytes  *int64     `json:"size_bytes,omitempty"`
	Status     string     `json:"status"`
	ErrorClass *string    `json:"error_class,omitempty"`
	CreatedAt  time.Time  `json:"created_at"`
	UpdatedAt  time.Time  `json:"updated_at"`
}

type AIJob struct {
	ID             uuid.UUID       `json:"id"`
	TenantID       uuid.UUID       `json:"tenant_id"`
	Type           string          `json:"type"`
	Status         string          `json:"status"`
	Payload        json.RawMessage `json:"payload"`
	Result         json.RawMessage `json:"result,omitempty"`
	ErrorClass     *string         `json:"error_class,omitempty"`
	ErrorMessage   *string         `json:"error_message,omitempty"`
	IdempotencyKey string          `json:"idempotency_key"`
	AttemptCount   int32           `json:"attempt_count"`
	MaxAttempts    int32           `json:"max_attempts"`
	RunAfter       time.Time       `json:"run_after"`
	LockedBy       *string         `json:"locked_by,omitempty"`
	LeaseExpiresAt *time.Time      `json:"lease_expires_at,omitempty"`
	StartedAt      *time.Time      `json:"started_at,omitempty"`
	FinishedAt     *time.Time      `json:"finished_at,omitempty"`
	CreatedAt      time.Time       `json:"created_at"`
	UpdatedAt      time.Time       `json:"updated_at"`
}

type AIJobAttempt struct {
	ID            uuid.UUID  `json:"id"`
	JobID         uuid.UUID  `json:"job_id"`
	AttemptNumber int32      `json:"attempt_number"`
	Status        string     `json:"status"`
	ErrorClass    *string    `json:"error_class,omitempty"`
	ErrorMessage  *string    `json:"error_message,omitempty"`
	DurationMS    *int32     `json:"duration_ms,omitempty"`
	StartedAt     time.Time  `json:"started_at"`
	FinishedAt    *time.Time `json:"finished_at,omitempty"`
}

type Tenant struct {
	ID        uuid.UUID `json:"id"`
	Name      string    `json:"name"`
	Slug      string    `json:"slug"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

type User struct {
	ID        uuid.UUID `json:"id"`
	TenantID  uuid.UUID `json:"tenant_id"`
	Email     string    `json:"email"`
	FullName  *string   `json:"full_name,omitempty"`
	Role      string    `json:"role"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

type AuthSession struct {
	TokenHash  string    `json:"-"`
	TenantID   uuid.UUID `json:"tenant_id"`
	UserID     uuid.UUID `json:"user_id"`
	ExpiresAt  time.Time `json:"expires_at"`
	CreatedAt  time.Time `json:"created_at"`
	LastUsedAt time.Time `json:"last_used_at"`
}

type AuthContext struct {
	Tenant  Tenant      `json:"tenant"`
	User    User        `json:"user"`
	Session AuthSession `json:"session"`
}

type JobTicket struct {
	ID                  uuid.UUID  `json:"id"`
	TenantID            uuid.UUID  `json:"tenant_id"`
	VoiceNoteID         *uuid.UUID `json:"voice_note_id,omitempty"`
	TranscriptID        *uuid.UUID `json:"transcript_id,omitempty"`
	Status              string     `json:"status"`
	Source              string     `json:"source"`
	CustomerName        *string    `json:"customer_name,omitempty"`
	CustomerPhone       *string    `json:"customer_phone,omitempty"`
	ServiceAddress      *string    `json:"service_address,omitempty"`
	TradeType           *string    `json:"trade_type,omitempty"`
	IssueSummary        *string    `json:"issue_summary,omitempty"`
	DetailedDescription *string    `json:"detailed_description,omitempty"`
	Priority            *string    `json:"priority,omitempty"`
	PreferredVisitTime  *string    `json:"preferred_visit_time,omitempty"`
	RequiredSkills      []string   `json:"required_skills"`
	SuggestedParts      []string   `json:"suggested_parts"`
	SafetyConcerns      []string   `json:"safety_concerns"`
	WarrantyMention     *bool      `json:"warranty_mention,omitempty"`
	FollowUpQuestions   []string   `json:"follow_up_questions"`
	Confidence          *float64   `json:"confidence,omitempty"`
	HumanReviewRequired bool       `json:"human_review_required"`
	ApprovedBy          *uuid.UUID `json:"approved_by,omitempty"`
	ApprovedAt          *time.Time `json:"approved_at,omitempty"`
	RejectedReason      *string    `json:"rejected_reason,omitempty"`
	RejectedAt          *time.Time `json:"rejected_at,omitempty"`
	CreatedAt           time.Time  `json:"created_at"`
	UpdatedAt           time.Time  `json:"updated_at"`
}

type HumanReview struct {
	ID             uuid.UUID       `json:"id"`
	TenantID       uuid.UUID       `json:"tenant_id"`
	JobTicketID    *uuid.UUID      `json:"job_ticket_id,omitempty"`
	AIJobID        *uuid.UUID      `json:"ai_job_id,omitempty"`
	VoiceNoteID    *uuid.UUID      `json:"voice_note_id,omitempty"`
	TranscriptID   *uuid.UUID      `json:"transcript_id,omitempty"`
	AIExtractionID *uuid.UUID      `json:"ai_extraction_id,omitempty"`
	Reason         string          `json:"reason"`
	Status         string          `json:"status"`
	ReviewerID     *uuid.UUID      `json:"reviewer_id,omitempty"`
	Correction     json.RawMessage `json:"correction,omitempty"`
	Notes          *string         `json:"notes,omitempty"`
	CreatedAt      time.Time       `json:"created_at"`
	ResolvedAt     *time.Time      `json:"resolved_at,omitempty"`
}
