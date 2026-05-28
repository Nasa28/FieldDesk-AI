from __future__ import annotations

import time
from typing import Any

import structlog

from fielddesk_worker.db_queries import (
    get_ticket_for_rag,
    hybrid_search,
    insert_model_call,
    insert_rag_query,
)
from fielddesk_worker.embeddings.service import _make_provider as _make_embedding_provider
from fielddesk_worker.providers.base import CallMetrics

log = structlog.get_logger()


def retrieve(job: dict[str, Any], cur) -> dict[str, Any]:
    """Worker handler for `rag` jobs.

    Two flavors of payload:

      Ticket-bound (auto-enqueued after extraction):
          {"ticket_id": "<uuid>", "top_k": 5}
        Builds the query from the ticket's trade_type + issue_summary +
        detailed_description, embeds it, runs hybrid search, persists a
        rag_queries row with job_ticket_id set. UI shows this on the ticket.

      Ad-hoc (POST /v1/rag/search):
          {"query_text": "...", "top_k": 5, "source": "ad_hoc"}
        Embeds the literal query, runs hybrid search, persists a
        rag_queries row with job_ticket_id NULL. The job result also
        contains the chunks so a polling client can pick them up directly
        without joining rag_queries.
    """
    tenant_id = str(job["tenant_id"])
    payload = job.get("payload") or {}
    top_k = int(payload.get("top_k") or 5)
    if top_k < 1:
        top_k = 1
    if top_k > 25:
        top_k = 25

    ticket_id_raw = payload.get("ticket_id")
    if ticket_id_raw:
        ticket = get_ticket_for_rag(cur, ticket_id=ticket_id_raw, tenant_id=tenant_id)
        if ticket is None:
            raise ValueError(f"ticket {ticket_id_raw} not found for tenant {tenant_id}")
        query_text = _build_query_from_ticket(ticket)
    else:
        query_text = str(payload.get("query_text") or "").strip()
    if not query_text:
        raise ValueError("rag job payload yielded no query text")

    provider = _make_embedding_provider()
    started = time.perf_counter()
    vectors, metrics = provider.embed([query_text])
    duration_ms = int((time.perf_counter() - started) * 1000)
    if not vectors:
        raise RuntimeError("embedding provider returned no vector for the query")

    embedding_literal = _format_halfvec_literal(vectors[0])

    raw_results = hybrid_search(
        cur,
        tenant_id=tenant_id,
        embedding_literal=embedding_literal,
        query_text=query_text,
        top_k=top_k,
    )
    results = [_clean_result_row(r) for r in raw_results]

    # Cost attribution: one ai_model_calls row for the embedding (the
    # retrieval itself is plain Postgres, no provider charge).
    _log_embed_call(cur, job, metrics, query_text)

    rag_query_id = insert_rag_query(
        cur,
        tenant_id=tenant_id,
        job_ticket_id=ticket_id_raw,
        query_text=query_text,
        top_k=top_k,
        results=results,
        embedding_model=metrics.model,
        cost_usd=metrics.cost_usd,
        duration_ms=duration_ms,
    )

    log.info(
        "rag_retrieval",
        rag_query_id=rag_query_id,
        ticket_id=str(ticket_id_raw) if ticket_id_raw else None,
        chunks=len(results),
        cost_usd=metrics.cost_usd,
        duration_ms=duration_ms,
    )
    return {
        "rag_query_id": rag_query_id,
        "ticket_id": str(ticket_id_raw) if ticket_id_raw else None,
        "chunks": len(results),
        "results": results,
        "cost_usd": metrics.cost_usd,
        "duration_ms": duration_ms,
        "embedding_model": metrics.model,
    }


def _build_query_from_ticket(ticket: dict[str, Any]) -> str:
    """Compose the natural-language query the ticket retrieval will run.

    Why we join several fields: a one-field query like "leak" is too vague
    for the lexical channel, and the dense channel can already mis-rank.
    Combining trade_type + issue_summary + detailed_description gives both
    channels enough signal without overfitting on customer-name PII.
    """
    parts: list[str] = []
    for key in ("trade_type", "issue_summary", "detailed_description"):
        value = ticket.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts).strip()


def _format_halfvec_literal(vec: list[float]) -> str:
    """Postgres-accepted literal form for halfvec inputs. The driver doesn't
    have native halfvec encoding so we build the string in Python."""
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


def _clean_result_row(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce DB rows to JSON-safe types. uuid.UUID and datetime aren't
    JSON-serializable by default; psycopg returns them natively."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "hex") and not isinstance(v, (bytes, bytearray)):
            out[k] = str(v)  # uuid.UUID
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out


def _log_embed_call(
    cur, job: dict[str, Any], metrics: CallMetrics, query_text: str
) -> None:
    insert_model_call(
        cur,
        tenant_id=job["tenant_id"],
        job_id=job.get("id"),
        kind="embedding",
        provider=metrics.provider,
        model=metrics.model,
        duration_ms=metrics.duration_ms,
        success=metrics.success,
        input_tokens=metrics.input_tokens,
        output_tokens=metrics.output_tokens,
        cost_usd=metrics.cost_usd,
        request_meta={
            "purpose": "rag_query_embed",
            "query_text_preview": query_text[:200],
        },
        durable=False,
    )
