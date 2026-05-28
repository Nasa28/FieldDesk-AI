package database

import (
	"context"
	"encoding/json"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"
)

// FailureFeedRow is one item in the unified failures dashboard. It collapses
// two distinct schemas (a failed `ai_model_calls` row and a failed/stuck
// `ai_jobs` row) into one shape so the UI can render them in the same table.
// item_type is the discriminator; some fields are null for the wrong side.
type FailureFeedRow struct {
	ID             uuid.UUID       `json:"id"`
	ItemType       string          `json:"item_type"`
	TenantID       uuid.UUID       `json:"tenant_id"`
	JobID          *uuid.UUID      `json:"job_id,omitempty"`
	Kind           string          `json:"kind"`
	Provider       *string         `json:"provider,omitempty"`
	Model          *string         `json:"model,omitempty"`
	Status         string          `json:"status"`
	InputTokens    int32           `json:"input_tokens"`
	OutputTokens   int32           `json:"output_tokens"`
	DurationMS     int32           `json:"duration_ms"`
	CostUSD        float64         `json:"cost_usd"`
	ErrorClass     *string         `json:"error_class,omitempty"`
	ErrorMessage   *string         `json:"error_message,omitempty"`
	AttemptCount   *int32          `json:"attempt_count,omitempty"`
	MaxAttempts    *int32          `json:"max_attempts,omitempty"`
	LockedBy       *string         `json:"locked_by,omitempty"`
	LeaseExpiresAt *time.Time      `json:"lease_expires_at,omitempty"`
	RequestMeta    json.RawMessage `json:"request_meta,omitempty"`
	ResponseMeta   json.RawMessage `json:"response_meta,omitempty"`
	CreatedAt      time.Time       `json:"created_at"`
}

type ListFailureFeedParams struct {
	TenantID uuid.UUID
	Window   TimeWindow
	Kind     string
	Provider string
	Cursor   *LogCursor
	Limit    int32
}

// ListFailureFeed powers /admin/failures. It combines failed provider calls
// with failed/needs-review/stuck jobs so the failure dashboard reflects
// pipeline health, not just provider exceptions. A "stuck" job is one in
// 'processing' whose lease expired without a heartbeat — those would
// otherwise be invisible until the next claim sweep.
func ListFailureFeed(ctx context.Context, db *DB, p ListFailureFeedParams) ([]FailureFeedRow, error) {
	limit := p.Limit
	if limit <= 0 || limit > 200 {
		limit = 50
	}

	const q = `
		WITH failure_items AS (
			SELECT
				'model_call'::text AS item_type,
				id,
				tenant_id,
				job_id,
				kind,
				provider,
				model,
				'provider_failed'::text AS status,
				input_tokens,
				output_tokens,
				duration_ms,
				cost_usd,
				error_class,
				error_message,
				NULL::integer AS attempt_count,
				NULL::integer AS max_attempts,
				NULL::text AS locked_by,
				NULL::timestamptz AS lease_expires_at,
				request_meta,
				response_meta,
				created_at
			FROM ai_model_calls
			WHERE tenant_id = $1
			  AND success = false
			  AND ($4::text = '' OR kind = $4)
			  AND ($5::text = '' OR provider = $5)

			UNION ALL

			SELECT
				'job'::text AS item_type,
				id,
				tenant_id,
				id AS job_id,
				type AS kind,
				NULL::text AS provider,
				NULL::text AS model,
				CASE
					WHEN status = 'processing' AND lease_expires_at < now()
						THEN 'stuck_processing'
					ELSE status
				END AS status,
				0 AS input_tokens,
				0 AS output_tokens,
				CASE
					WHEN started_at IS NULL THEN 0
					ELSE GREATEST(
						0,
						(EXTRACT(EPOCH FROM (COALESCE(finished_at, updated_at, now()) - started_at)) * 1000)::int
					)
				END AS duration_ms,
				0::numeric(12,6) AS cost_usd,
				error_class,
				error_message,
				attempt_count,
				max_attempts,
				locked_by,
				lease_expires_at,
				payload AS request_meta,
				COALESCE(result, '{}'::jsonb) AS response_meta,
				COALESCE(finished_at, updated_at, created_at) AS created_at
			FROM ai_jobs
			WHERE tenant_id = $1
			  AND (
				status IN ('failed', 'needs_review')
				OR (status = 'processing' AND lease_expires_at < now())
			  )
			  AND ($4::text = '' OR type = $4)
			  AND $5::text = ''
		)
		SELECT
			item_type, id, tenant_id, job_id, kind, provider, model, status,
			input_tokens, output_tokens, duration_ms, cost_usd,
			error_class, error_message, attempt_count, max_attempts,
			locked_by, lease_expires_at, request_meta, response_meta, created_at
		FROM failure_items
		WHERE tenant_id = $1
		  AND created_at >= $2
		  AND created_at <  $3
		  AND (
		        $6::timestamptz IS NULL
		        OR created_at < $6
		        OR (created_at = $6 AND id < $7::uuid)
		      )
		ORDER BY created_at DESC, id DESC
		LIMIT $8
	`
	var cursorAt *time.Time
	var cursorID *uuid.UUID
	if p.Cursor != nil {
		cursorAt = &p.Cursor.CreatedAt
		cursorID = &p.Cursor.ID
	}
	rows, err := db.Query(ctx, q,
		p.TenantID, p.Window.Start, p.Window.End,
		p.Kind, p.Provider, cursorAt, cursorID, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]FailureFeedRow, 0)
	for rows.Next() {
		var r FailureFeedRow
		var cost pgtype.Numeric
		var requestMeta, responseMeta []byte
		if err := rows.Scan(
			&r.ItemType, &r.ID, &r.TenantID, &r.JobID, &r.Kind, &r.Provider, &r.Model,
			&r.Status, &r.InputTokens, &r.OutputTokens, &r.DurationMS, &cost,
			&r.ErrorClass, &r.ErrorMessage, &r.AttemptCount, &r.MaxAttempts,
			&r.LockedBy, &r.LeaseExpiresAt, &requestMeta, &responseMeta, &r.CreatedAt,
		); err != nil {
			return nil, err
		}
		r.CostUSD = numericToFloat(cost)
		r.RequestMeta = json.RawMessage(requestMeta)
		r.ResponseMeta = json.RawMessage(responseMeta)
		out = append(out, r)
	}
	return out, rows.Err()
}
