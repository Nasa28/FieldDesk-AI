package database

import (
	"context"
	"encoding/json"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"
)

type TimeWindow struct {
	Start time.Time
	End   time.Time
}

type LogCursor struct {
	CreatedAt time.Time
	ID        uuid.UUID
}

type CostRollup struct {
	TotalCostUSD    float64 `json:"total_cost_usd"`
	SuccessCostUSD  float64 `json:"success_cost_usd"`
	FailedCostUSD   float64 `json:"failed_cost_usd"`
	InputTokens     int64   `json:"input_tokens"`
	OutputTokens    int64   `json:"output_tokens"`
	TotalCalls      int64   `json:"total_calls"`
	SuccessfulCalls int64   `json:"successful_calls"`
	FailedCalls     int64   `json:"failed_calls"`
}

func CostRollupForTenant(ctx context.Context, db *DB, tenantID uuid.UUID, w TimeWindow) (CostRollup, error) {
	const q = `
		SELECT
			COALESCE(SUM(cost_usd),                            0)::numeric(14,6),
			COALESCE(SUM(cost_usd) FILTER (WHERE success),     0)::numeric(14,6),
			COALESCE(SUM(cost_usd) FILTER (WHERE NOT success), 0)::numeric(14,6),
			COALESCE(SUM(input_tokens),                        0)::bigint,
			COALESCE(SUM(output_tokens),                       0)::bigint,
			COUNT(*)::bigint,
			COUNT(*) FILTER (WHERE success)::bigint,
			COUNT(*) FILTER (WHERE NOT success)::bigint
		FROM ai_model_calls
		WHERE tenant_id = $1
		  AND created_at >= $2
		  AND created_at <  $3
	`
	var r CostRollup
	var total, success, failed pgtype.Numeric
	err := db.QueryRow(ctx, q, tenantID, w.Start, w.End).Scan(
		&total, &success, &failed,
		&r.InputTokens, &r.OutputTokens,
		&r.TotalCalls, &r.SuccessfulCalls, &r.FailedCalls,
	)
	if err != nil {
		return CostRollup{}, err
	}
	r.TotalCostUSD = numericToFloat(total)
	r.SuccessCostUSD = numericToFloat(success)
	r.FailedCostUSD = numericToFloat(failed)
	return r, nil
}

type CostByKindRow struct {
	Kind          string  `json:"kind"`
	TotalCostUSD  float64 `json:"total_cost_usd"`
	FailedCostUSD float64 `json:"failed_cost_usd"`
	TotalCalls    int64   `json:"total_calls"`
	FailedCalls   int64   `json:"failed_calls"`
}

func CostByKind(ctx context.Context, db *DB, tenantID uuid.UUID, w TimeWindow) ([]CostByKindRow, error) {
	const q = `
		SELECT
			kind,
			COALESCE(SUM(cost_usd),                            0)::numeric(14,6),
			COALESCE(SUM(cost_usd) FILTER (WHERE NOT success), 0)::numeric(14,6),
			COUNT(*)::bigint,
			COUNT(*) FILTER (WHERE NOT success)::bigint
		FROM ai_model_calls
		WHERE tenant_id = $1
		  AND created_at >= $2
		  AND created_at <  $3
		GROUP BY kind
		ORDER BY 2 DESC
	`
	rows, err := db.Query(ctx, q, tenantID, w.Start, w.End)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]CostByKindRow, 0)
	for rows.Next() {
		var r CostByKindRow
		var total, failed pgtype.Numeric
		if err := rows.Scan(&r.Kind, &total, &failed, &r.TotalCalls, &r.FailedCalls); err != nil {
			return nil, err
		}
		r.TotalCostUSD = numericToFloat(total)
		r.FailedCostUSD = numericToFloat(failed)
		out = append(out, r)
	}
	return out, rows.Err()
}

type CostByModelRow struct {
	Provider      string  `json:"provider"`
	Model         string  `json:"model"`
	TotalCostUSD  float64 `json:"total_cost_usd"`
	FailedCostUSD float64 `json:"failed_cost_usd"`
	InputTokens   int64   `json:"input_tokens"`
	OutputTokens  int64   `json:"output_tokens"`
	TotalCalls    int64   `json:"total_calls"`
	FailedCalls   int64   `json:"failed_calls"`
}

func CostByModel(ctx context.Context, db *DB, tenantID uuid.UUID, w TimeWindow) ([]CostByModelRow, error) {
	const q = `
		SELECT
			provider,
			model,
			COALESCE(SUM(cost_usd),                            0)::numeric(14,6),
			COALESCE(SUM(cost_usd) FILTER (WHERE NOT success), 0)::numeric(14,6),
			COALESCE(SUM(input_tokens),                        0)::bigint,
			COALESCE(SUM(output_tokens),                       0)::bigint,
			COUNT(*)::bigint,
			COUNT(*) FILTER (WHERE NOT success)::bigint
		FROM ai_model_calls
		WHERE tenant_id = $1
		  AND created_at >= $2
		  AND created_at <  $3
		GROUP BY provider, model
		ORDER BY 3 DESC
	`
	rows, err := db.Query(ctx, q, tenantID, w.Start, w.End)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]CostByModelRow, 0)
	for rows.Next() {
		var r CostByModelRow
		var total, failed pgtype.Numeric
		if err := rows.Scan(
			&r.Provider, &r.Model, &total, &failed,
			&r.InputTokens, &r.OutputTokens, &r.TotalCalls, &r.FailedCalls,
		); err != nil {
			return nil, err
		}
		r.TotalCostUSD = numericToFloat(total)
		r.FailedCostUSD = numericToFloat(failed)
		out = append(out, r)
	}
	return out, rows.Err()
}

type LatencyByKindRow struct {
	Kind        string `json:"kind"`
	SampleCalls int64  `json:"sample_calls"`
	P50MS       int32  `json:"p50_ms"`
	P95MS       int32  `json:"p95_ms"`
	MaxMS       int32  `json:"max_ms"`
}

func LatencyPercentilesByKind(ctx context.Context, db *DB, tenantID uuid.UUID, w TimeWindow) ([]LatencyByKindRow, error) {
	const q = `
		SELECT
			kind,
			COUNT(*)::bigint,
			COALESCE(percentile_cont(0.5)  WITHIN GROUP (ORDER BY duration_ms), 0)::int,
			COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms), 0)::int,
			COALESCE(MAX(duration_ms),                                          0)::int
		FROM ai_model_calls
		WHERE tenant_id = $1
		  AND created_at >= $2
		  AND created_at <  $3
		  AND success = true
		GROUP BY kind
		ORDER BY kind
	`
	rows, err := db.Query(ctx, q, tenantID, w.Start, w.End)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]LatencyByKindRow, 0)
	for rows.Next() {
		var r LatencyByKindRow
		if err := rows.Scan(&r.Kind, &r.SampleCalls, &r.P50MS, &r.P95MS, &r.MaxMS); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

type JobMetrics struct {
	TotalJobs       int64 `json:"total_jobs"`
	PendingJobs     int64 `json:"pending_jobs"`
	ProcessingJobs  int64 `json:"processing_jobs"`
	RetryingJobs    int64 `json:"retrying_jobs"`
	NeedsReviewJobs int64 `json:"needs_review_jobs"`
	SucceededJobs   int64 `json:"succeeded_jobs"`
	FailedJobs      int64 `json:"failed_jobs"`
	RetriedJobs     int64 `json:"retried_jobs"`
}

func JobMetricsForTenant(ctx context.Context, db *DB, tenantID uuid.UUID, w TimeWindow) (JobMetrics, error) {
	const q = `
		SELECT
			COUNT(*)::bigint,
			COUNT(*) FILTER (WHERE status = 'pending')::bigint,
			COUNT(*) FILTER (WHERE status = 'processing')::bigint,
			COUNT(*) FILTER (WHERE status = 'retrying')::bigint,
			COUNT(*) FILTER (WHERE status = 'needs_review')::bigint,
			COUNT(*) FILTER (WHERE status = 'succeeded')::bigint,
			COUNT(*) FILTER (WHERE status = 'failed')::bigint,
			COUNT(*) FILTER (WHERE attempt_count > 1)::bigint
		FROM ai_jobs
		WHERE tenant_id = $1
		  AND created_at >= $2
		  AND created_at <  $3
	`
	var m JobMetrics
	err := db.QueryRow(ctx, q, tenantID, w.Start, w.End).Scan(
		&m.TotalJobs, &m.PendingJobs, &m.ProcessingJobs, &m.RetryingJobs,
		&m.NeedsReviewJobs, &m.SucceededJobs, &m.FailedJobs, &m.RetriedJobs,
	)
	return m, err
}

type ModelCallRow struct {
	ID           uuid.UUID       `json:"id"`
	TenantID     uuid.UUID       `json:"tenant_id"`
	JobID        *uuid.UUID      `json:"job_id,omitempty"`
	Kind         string          `json:"kind"`
	Provider     string          `json:"provider"`
	Model        string          `json:"model"`
	InputTokens  int32           `json:"input_tokens"`
	OutputTokens int32           `json:"output_tokens"`
	DurationMS   int32           `json:"duration_ms"`
	CostUSD      float64         `json:"cost_usd"`
	Success      bool            `json:"success"`
	ErrorClass   *string         `json:"error_class,omitempty"`
	ErrorMessage *string         `json:"error_message,omitempty"`
	RequestMeta  json.RawMessage `json:"request_meta,omitempty"`
	ResponseMeta json.RawMessage `json:"response_meta,omitempty"`
	CreatedAt    time.Time       `json:"created_at"`
}

// ListModelCallsParams scopes the listing. SuccessFilter accepts "all" | "success" | "failed".
// Cursor pagination uses (created_at, id) to avoid skipping rows with identical timestamps.
type ListModelCallsParams struct {
	TenantID      uuid.UUID
	Window        TimeWindow
	Kind          string
	Provider      string
	SuccessFilter string
	Cursor        *LogCursor
	Limit         int32
}

func ListModelCalls(ctx context.Context, db *DB, p ListModelCallsParams) ([]ModelCallRow, error) {
	successFilter := p.SuccessFilter
	if successFilter == "" {
		successFilter = "all"
	}
	limit := p.Limit
	if limit <= 0 || limit > 500 {
		limit = 100
	}

	const q = `
		SELECT
			id, tenant_id, job_id, kind, provider, model,
			input_tokens, output_tokens, duration_ms, cost_usd,
			success, error_class, error_message, request_meta, response_meta, created_at
		FROM ai_model_calls
		WHERE tenant_id = $1
		  AND created_at >= $2
		  AND created_at <  $3
		  AND ($4::text = '' OR kind     = $4)
		  AND ($5::text = '' OR provider = $5)
		  AND (
		        $6::text = 'all'
		        OR ($6::text = 'success' AND success = true)
		        OR ($6::text = 'failed'  AND success = false)
		      )
		  AND (
		        $7::timestamptz IS NULL
		        OR created_at < $7
		        OR (created_at = $7 AND id < $8::uuid)
		      )
		ORDER BY created_at DESC, id DESC
		LIMIT $9
	`
	var cursorAt *time.Time
	var cursorID *uuid.UUID
	if p.Cursor != nil {
		cursorAt = &p.Cursor.CreatedAt
		cursorID = &p.Cursor.ID
	}
	rows, err := db.Query(ctx, q,
		p.TenantID, p.Window.Start, p.Window.End,
		p.Kind, p.Provider, successFilter,
		cursorAt, cursorID, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]ModelCallRow, 0)
	for rows.Next() {
		var r ModelCallRow
		var cost pgtype.Numeric
		var requestMeta, responseMeta []byte
		if err := rows.Scan(
			&r.ID, &r.TenantID, &r.JobID, &r.Kind, &r.Provider, &r.Model,
			&r.InputTokens, &r.OutputTokens, &r.DurationMS, &cost,
			&r.Success, &r.ErrorClass, &r.ErrorMessage, &requestMeta, &responseMeta,
			&r.CreatedAt,
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

// numericToFloat converts a pgtype.Numeric to float64 for JSON output.
// Cost values fit comfortably in float64; the underlying column is NUMERIC(12,6).
func numericToFloat(n pgtype.Numeric) float64 {
	if !n.Valid {
		return 0
	}
	f, err := n.Float64Value()
	if err != nil || !f.Valid {
		return 0
	}
	return f.Float64
}
