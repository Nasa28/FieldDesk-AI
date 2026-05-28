# lint-tenant-filter: every query in this file filters by tenant_id; see WHERE clauses.
from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from fielddesk_worker.db_queries._helpers import returned_id


def get_ticket_with_latest_rag(
    cur,
    *,
    ticket_id: str | UUID,
    tenant_id: str | UUID,
    rag_query_id: str | UUID | None = None,
) -> dict[str, Any] | None:
    """Single round-trip: pull the ticket fields we need for the synthesis
    prompt, plus a rag_queries row for that ticket.

    Returning a unified dict (rather than two queries) keeps the worker
    handler readable and lets the tenant_id filter apply once to both tables.
    When rag_query_id is supplied, bind to that exact retrieval; otherwise
    fall back to the freshest row for manual/backfill calls.
    """
    requested_rag_query_id = str(rag_query_id) if rag_query_id else None
    cur.execute(
        """
        SELECT
            t.id                AS ticket_id,
            t.tenant_id         AS tenant_id,
            t.trade_type        AS trade_type,
            t.issue_summary     AS issue_summary,
            t.detailed_description AS detailed_description,
            t.priority          AS priority,
            rq.id               AS rag_query_id,
            rq.query_text       AS rag_query_text,
            rq.results          AS rag_results,
            rq.embedding_model  AS rag_embedding_model
        FROM job_tickets t
        LEFT JOIN LATERAL (
            SELECT id, query_text, results, embedding_model
            FROM rag_queries
            WHERE job_ticket_id = t.id AND tenant_id = t.tenant_id
              AND (%s::uuid IS NULL OR id = %s::uuid)
            ORDER BY created_at DESC
            LIMIT 1
        ) rq ON true
        WHERE t.id = %s AND t.tenant_id = %s
        """,
        (requested_rag_query_id, requested_rag_query_id, str(ticket_id), str(tenant_id)),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def insert_ticket_recommendation(
    cur,
    *,
    tenant_id: str | UUID,
    job_ticket_id: str | UUID,
    rag_query_id: str | UUID | None,
    output: dict[str, Any],
    confidence: float | None,
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    duration_ms: int,
    json_valid: bool,
    error_message: str | None,
) -> str:
    cur.execute(
        """
        INSERT INTO ticket_recommendations
            (tenant_id, job_ticket_id, rag_query_id, output, confidence,
             provider, model, prompt_version, schema_version,
             input_tokens, output_tokens, cost_usd, duration_ms,
             json_valid, error_message)
        VALUES (%s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s)
        RETURNING id
        """,
        (
            str(tenant_id),
            str(job_ticket_id),
            str(rag_query_id) if rag_query_id else None,
            Jsonb(output),
            confidence,
            provider,
            model,
            prompt_version,
            schema_version,
            input_tokens,
            output_tokens,
            cost_usd,
            duration_ms,
            json_valid,
            error_message,
        ),
    )
    return returned_id(cur.fetchone())
