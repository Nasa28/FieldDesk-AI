from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb


def get_ticket_for_rag(
    cur, *, ticket_id: str | UUID, tenant_id: str | UUID
) -> dict[str, Any] | None:
    """Pull the fields we use to build a retrieval query from a ticket."""
    cur.execute(
        """
        SELECT id, tenant_id, trade_type, issue_summary, detailed_description,
               customer_name, service_address
        FROM job_tickets
        WHERE id = %s AND tenant_id = %s
        """,
        (str(ticket_id), str(tenant_id)),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def hybrid_search(
    cur,
    *,
    tenant_id: str | UUID,
    embedding_literal: str,
    query_text: str,
    top_k: int = 5,
    candidates: int = 50,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Run the same hybrid SQL the Go side runs.

    If this drifts from apps/api/internal/database/rag.go:HybridSearch, the
    Go API and the worker will return different chunks for the same query.
    The literal SQL is duplicated deliberately (rather than calling Go via
    HTTP, or extracting to a PG function) because the cost of one duplicated
    query is lower than the cost of either alternative right now. Tests on
    both sides should catch drift.
    """
    cur.execute(
        """
WITH dense AS (
    SELECT
        c.id,
        c.document_id,
        c.text,
        c.heading_path,
        c.source_page,
        c.source_locator,
        ROW_NUMBER() OVER (ORDER BY c.embedding <=> %s::halfvec) AS rank_dense
    FROM document_chunks c
    WHERE c.tenant_id = %s
    ORDER BY c.embedding <=> %s::halfvec
    LIMIT %s
),
lexical AS (
    SELECT
        c.id,
        c.document_id,
        c.text,
        c.heading_path,
        c.source_page,
        c.source_locator,
        ROW_NUMBER() OVER (
            ORDER BY ts_rank_cd(c.text_search, websearch_to_tsquery('english', %s)) DESC
        ) AS rank_lexical
    FROM document_chunks c
    WHERE c.tenant_id = %s
      AND (%s = '' OR c.text_search @@ websearch_to_tsquery('english', %s))
    ORDER BY ts_rank_cd(c.text_search, websearch_to_tsquery('english', %s)) DESC
    LIMIT %s
),
fused AS (
    SELECT
        COALESCE(d.id, l.id)              AS chunk_id,
        COALESCE(d.document_id, l.document_id) AS document_id,
        COALESCE(d.text, l.text)          AS text,
        COALESCE(d.heading_path, l.heading_path) AS heading_path,
        COALESCE(d.source_page, l.source_page)   AS source_page,
        COALESCE(d.source_locator, l.source_locator) AS source_locator,
        d.rank_dense,
        l.rank_lexical,
        (CASE WHEN d.rank_dense   IS NULL THEN 0.0 ELSE 1.0 / (%s + d.rank_dense)   END
       + CASE WHEN l.rank_lexical IS NULL THEN 0.0 ELSE 1.0 / (%s + l.rank_lexical) END) AS fused_score
    FROM dense d
    FULL OUTER JOIN lexical l ON l.id = d.id
)
SELECT
    f.chunk_id,
    f.document_id,
    docs.title       AS document_title,
    f.text,
    f.heading_path,
    f.source_page,
    f.source_locator,
    f.rank_dense,
    f.rank_lexical,
    f.fused_score
FROM fused f
JOIN documents docs ON docs.id = f.document_id AND docs.tenant_id = %s
WHERE f.fused_score > 0
ORDER BY f.fused_score DESC
LIMIT %s
        """,
        (
            embedding_literal, str(tenant_id), embedding_literal, candidates,  # dense CTE
            query_text, str(tenant_id), query_text, query_text, query_text, candidates,  # lexical CTE
            rrf_k, rrf_k,  # fused
            str(tenant_id), top_k,  # final
        ),
    )
    return [dict(r) for r in cur.fetchall()]


def insert_rag_query(
    cur,
    *,
    tenant_id: str | UUID,
    job_ticket_id: str | UUID | None,
    query_text: str,
    top_k: int,
    results: list[dict[str, Any]],
    embedding_model: str,
    cost_usd: float,
    duration_ms: int,
) -> str:
    cur.execute(
        """
        INSERT INTO rag_queries
            (tenant_id, job_ticket_id, query_text, top_k, results,
             embedding_model, cost_usd, duration_ms)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            str(tenant_id),
            str(job_ticket_id) if job_ticket_id else None,
            query_text,
            top_k,
            Jsonb(results),
            embedding_model,
            cost_usd,
            duration_ms,
        ),
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("insert_rag_query returned no id")
    return str(row[0]) if not isinstance(row, dict) else str(row["id"])
