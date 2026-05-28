from __future__ import annotations

import time
from typing import Any

import structlog

from fielddesk_worker.db_queries import (
    enqueue_job,
    get_ticket_for_rag,
    insert_model_call,
    insert_rag_query,
    log_model_call_isolated,
)
from fielddesk_worker.embeddings.service import _make_provider as _make_embedding_provider
from fielddesk_worker.providers.base import CallMetrics
from fielddesk_worker.rag.retrieval import retrieve_with_optional_rerank
from fielddesk_worker.reranking import RerankerMetrics

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
          {"query_text": "...", "top_k": 5, "source": "ad_hoc", "answer": true}
        Embeds the literal query, runs hybrid search, persists a
        rag_queries row with job_ticket_id NULL. The job result also
        contains the chunks so a polling client can pick them up directly
        without joining rag_queries. When answer=true, the worker also
        synthesizes a grounded answer from those chunks.
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
    try:
        vectors, metrics = provider.embed([query_text])
    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.perf_counter() - started) * 1000)
        log_model_call_isolated(
            tenant_id=tenant_id,
            job_id=job.get("id"),
            kind="embedding",
            provider=provider.name,
            model=getattr(provider, "model", "?"),
            duration_ms=duration_ms,
            success=False,
            cost_usd=0.0,
            error_class=type(exc).__name__,
            error_message=str(exc)[:1000],
            request_meta={"purpose": "rag_query_embed", "query_text_preview": query_text[:200]},
        )
        raise
    duration_ms = int((time.perf_counter() - started) * 1000)
    # Cost attribution: one durable ai_model_calls row for the embedding. Log
    # before DB retrieval so a later SQL failure cannot erase a provider call.
    _log_embed_call(cur, job, metrics, query_text)
    if not vectors:
        raise RuntimeError("embedding provider returned no vector for the query")

    embedding_literal = _format_halfvec_literal(vectors[0])

    raw_results, rerank_metrics = retrieve_with_optional_rerank(
        cur,
        tenant_id=tenant_id,
        query_text=query_text,
        embedding_literal=embedding_literal,
        top_k=top_k,
    )
    results = [_clean_result_row(r) for r in raw_results]
    if rerank_metrics is not None:
        # Whether the rerank call succeeded or failed, it cost money (or
        # took time). One ai_model_calls row per RAG query so the cost
        # dashboard can split rerank spend from embedding spend.
        _log_rerank_call(cur, job, rerank_metrics, query_text)

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

    answer: dict[str, Any] | None = None
    if not ticket_id_raw and _truthy(payload.get("answer")):
        from fielddesk_worker.rag.answer import synthesize_answer

        answer = synthesize_answer(
            cur=cur,
            job=job,
            tenant_id=tenant_id,
            query_text=query_text,
            chunks=results,
            rag_query_id=str(rag_query_id),
        )

    # Phase 4.5: auto-enqueue the synthesis step for ticket-bound retrievals.
    # Idempotency key includes the rag_query_id so re-running rag on the same
    # ticket produces one synthesis per retrieval rather than spawning
    # duplicates that overwrite each other's cost rows.
    if ticket_id_raw:
        enqueue_job(
            cur,
            tenant_id=tenant_id,
            type_="draft_ticket",
            payload={
                "ticket_id": str(ticket_id_raw),
                "rag_query_id": str(rag_query_id),
                "source": "auto",
            },
            idempotency_key=f"recs:rag_query:{rag_query_id}",
        )

    log.info(
        "rag_retrieval",
        rag_query_id=rag_query_id,
        ticket_id=str(ticket_id_raw) if ticket_id_raw else None,
        chunks=len(results),
        answered=answer is not None,
        cost_usd=metrics.cost_usd,
        duration_ms=duration_ms,
    )
    response = {
        "rag_query_id": rag_query_id,
        "ticket_id": str(ticket_id_raw) if ticket_id_raw else None,
        "chunks": len(results),
        "results": results,
        "cost_usd": metrics.cost_usd,
        "duration_ms": duration_ms,
        "embedding_model": metrics.model,
    }
    if answer is not None:
        response["answer"] = answer
        response["answer_cost_usd"] = answer.get("cost_usd", 0.0)
    return response


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


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


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
    )


def _log_rerank_call(
    cur, job: dict[str, Any], metrics: RerankerMetrics, query_text: str
) -> None:
    """One ai_model_calls row per rerank invocation. Uses kind='rerank'
    which the schema's CHECK constraint already allows (added in 00006).
    """
    insert_model_call(
        cur,
        tenant_id=job["tenant_id"],
        job_id=job.get("id"),
        kind="rerank",
        provider=metrics.provider,
        model=metrics.model,
        duration_ms=metrics.duration_ms,
        success=metrics.success,
        input_tokens=0,
        output_tokens=0,
        cost_usd=metrics.cost_usd,
        error_class=metrics.error_class,
        error_message=metrics.error_message,
        request_meta={
            "purpose": "rag_rerank",
            "query_text_preview": query_text[:200],
            "candidate_count": metrics.candidate_count,
            **metrics.extra,
        },
    )
