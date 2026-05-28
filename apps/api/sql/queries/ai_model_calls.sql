-- name: CostRollupForTenant :one
-- Aggregate cost & call counts for a tenant in a time window.
-- Splits successful vs failed because failed calls still cost money.
SELECT
    COALESCE(SUM(cost_usd),                                      0)::numeric(14,6) AS total_cost_usd,
    COALESCE(SUM(cost_usd) FILTER (WHERE success),               0)::numeric(14,6) AS success_cost_usd,
    COALESCE(SUM(cost_usd) FILTER (WHERE NOT success),           0)::numeric(14,6) AS failed_cost_usd,
    COALESCE(SUM(input_tokens),                                  0)::bigint       AS input_tokens,
    COALESCE(SUM(output_tokens),                                 0)::bigint       AS output_tokens,
    COUNT(*)::bigint                                                              AS total_calls,
    COUNT(*) FILTER (WHERE success)::bigint                                       AS successful_calls,
    COUNT(*) FILTER (WHERE NOT success)::bigint                                   AS failed_calls
FROM ai_model_calls
WHERE tenant_id = $1
  AND created_at >= $2
  AND created_at <  $3;

-- name: CostByKind :many
SELECT
    kind,
    COALESCE(SUM(cost_usd),                            0)::numeric(14,6) AS total_cost_usd,
    COALESCE(SUM(cost_usd) FILTER (WHERE NOT success), 0)::numeric(14,6) AS failed_cost_usd,
    COUNT(*)::bigint                                                     AS total_calls,
    COUNT(*) FILTER (WHERE NOT success)::bigint                          AS failed_calls
FROM ai_model_calls
WHERE tenant_id = $1
  AND created_at >= $2
  AND created_at <  $3
GROUP BY kind
ORDER BY total_cost_usd DESC;

-- name: CostByModel :many
SELECT
    provider,
    model,
    COALESCE(SUM(cost_usd),                            0)::numeric(14,6) AS total_cost_usd,
    COALESCE(SUM(cost_usd) FILTER (WHERE NOT success), 0)::numeric(14,6) AS failed_cost_usd,
    COALESCE(SUM(input_tokens),                        0)::bigint        AS input_tokens,
    COALESCE(SUM(output_tokens),                       0)::bigint        AS output_tokens,
    COUNT(*)::bigint                                                     AS total_calls,
    COUNT(*) FILTER (WHERE NOT success)::bigint                          AS failed_calls
FROM ai_model_calls
WHERE tenant_id = $1
  AND created_at >= $2
  AND created_at <  $3
GROUP BY provider, model
ORDER BY total_cost_usd DESC;

-- name: LatencyPercentilesByKind :many
-- Percentile_cont over successful calls only; a failed call's duration is noise.
SELECT
    kind,
    COUNT(*)::bigint                                                          AS sample_calls,
    COALESCE(percentile_cont(0.5)  WITHIN GROUP (ORDER BY duration_ms), 0)::int AS p50_ms,
    COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms), 0)::int AS p95_ms,
    COALESCE(MAX(duration_ms),                                          0)::int AS max_ms
FROM ai_model_calls
WHERE tenant_id = $1
  AND created_at >= $2
  AND created_at <  $3
  AND success = true
GROUP BY kind
ORDER BY kind;

-- name: JobMetrics :one
-- Counts of ai_jobs by terminal/non-terminal status plus retry rate.
SELECT
    COUNT(*)::bigint                                                     AS total_jobs,
    COUNT(*) FILTER (WHERE status = 'pending')::bigint                   AS pending_jobs,
    COUNT(*) FILTER (WHERE status = 'processing')::bigint                AS processing_jobs,
    COUNT(*) FILTER (WHERE status = 'retrying')::bigint                  AS retrying_jobs,
    COUNT(*) FILTER (WHERE status = 'needs_review')::bigint              AS needs_review_jobs,
    COUNT(*) FILTER (WHERE status = 'succeeded')::bigint                 AS succeeded_jobs,
    COUNT(*) FILTER (WHERE status = 'failed')::bigint                    AS failed_jobs,
    COUNT(*) FILTER (WHERE attempt_count > 1)::bigint                    AS retried_jobs
FROM ai_jobs
WHERE tenant_id = $1
  AND created_at >= $2
  AND created_at <  $3;

-- name: ListModelCalls :many
-- Paginated log view. Cursor is (created_at, id) — both DESC. Filters are optional;
-- empty string for kind/provider means "no filter". `success_filter` accepts
-- 'all' | 'success' | 'failed'. Tenant scope is the outer WHERE.
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
LIMIT $9;

-- name: ListFailureFeed :many
-- Unified provider-call + job failure feed used by /admin/failures.
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
LIMIT $8;
