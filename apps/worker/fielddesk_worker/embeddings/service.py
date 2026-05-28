from __future__ import annotations

from typing import Any

import structlog

from fielddesk_worker.config import load_settings
from fielddesk_worker.db_queries import (
    delete_existing_chunks,
    get_document_for_update,
    insert_chunk,
    insert_model_call,
    log_model_call_isolated,
    update_document_status,
)
from fielddesk_worker.embeddings.chunker import chunk_segments
from fielddesk_worker.embeddings.contextual import (
    CONTEXTUAL_RETRIEVAL_VERSION,
    build_retrieval_text,
)
from fielddesk_worker.parsing import ParseError, SUPPORTED_MIME_TYPES, parse_document
from fielddesk_worker.providers.base import CallMetrics, EmbeddingProvider
from fielddesk_worker.storage import get_object_bytes

log = structlog.get_logger()


def _make_provider() -> EmbeddingProvider:
    s = load_settings()
    name = (s.embedding_provider or "stub").lower()
    if name == "stub":
        from fielddesk_worker.providers.stub_embedding import StubEmbeddingProvider

        return StubEmbeddingProvider()
    if name == "openai":
        if not s.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai"
            )
        from fielddesk_worker.providers.openai_embedding import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider(api_key=s.openai_api_key, model=s.embedding_model)
    raise ValueError(f"unknown EMBEDDING_PROVIDER: {s.embedding_provider!r}")


def embed(job: dict[str, Any], cur) -> dict[str, Any]:
    """Worker handler for `embed` jobs.

    Flow:
      1. Lock the documents row, switch status to 'processing'.
      2. Fetch object bytes from MinIO.
      3. Parse via the format-appropriate parser.
      4. Chunk into 512-token segments preserving heading_path / source_page.
      5. Build retrieval-only contextual text and call the embedding provider.
      6. Upsert chunks idempotently via the partial UNIQUE on content_hash.
      7. Log one ai_model_calls row, mark document 'ready'.

    On ParseError: mark document 'failed' with parse_error set, log a
    failed ai_model_calls row, return without raising. Anything else (storage
    fetch failure, embedding provider error) bubbles up to the queue's normal
    retry / needs_review path.
    """
    tenant_id = str(job["tenant_id"])
    payload = job.get("payload") or {}
    document_id = payload.get("document_id")
    if not document_id:
        raise ValueError("embed job payload missing document_id")

    document = get_document_for_update(
        cur, document_id=document_id, tenant_id=tenant_id
    )
    if document["mime_type"] not in SUPPORTED_MIME_TYPES:
        # Surface as parse_error rather than retry — the caps would just
        # land us back here. The API also validates on upload, so this
        # only fires for documents created before a parser was retired.
        _fail_document(
            cur,
            document_id=document_id,
            tenant_id=tenant_id,
            job_id=job.get("id"),
            parse_error=f"unsupported mime_type: {document['mime_type']}",
        )
        return {"chunks": 0, "skipped": True, "reason": "unsupported_mime"}

    update_document_status(
        cur, document_id=document_id, tenant_id=tenant_id, status="processing"
    )
    object_bytes = get_object_bytes(document["object_key"])

    try:
        segments = parse_document(object_bytes, document["mime_type"])
    except ParseError as exc:
        _fail_document(
            cur,
            document_id=document_id,
            tenant_id=tenant_id,
            job_id=job.get("id"),
            parse_error=str(exc),
        )
        return {"chunks": 0, "failed": True, "reason": "parse_error"}

    chunks = chunk_segments(segments)
    if not chunks:
        # Empty document is legitimate — mark ready with zero chunks rather
        # than failed. The retrieval side just won't return anything.
        update_document_status(
            cur, document_id=document_id, tenant_id=tenant_id, status="ready"
        )
        log_model_call_isolated(
            tenant_id=tenant_id,
            job_id=job.get("id"),
            kind="embedding",
            provider="stub",
            model="none",
            duration_ms=0,
            success=True,
            cost_usd=0.0,
            request_meta={"document_id": str(document_id), "empty": True},
        )
        return {"chunks": 0, "ready": True, "reason": "empty"}

    provider = _make_provider()
    retrieval_texts = [
        build_retrieval_text(
            document_title=str(document["title"] or ""),
            chunk=chunk,
        )
        for chunk in chunks
    ]
    try:
        vectors, metrics = provider.embed(retrieval_texts)
    except Exception as exc:  # noqa: BLE001
        # Log the failure (cost still applies if the provider charged us
        # mid-batch) before re-raising so the queue can retry.
        log_model_call_isolated(
            tenant_id=tenant_id,
            job_id=job.get("id"),
            kind="embedding",
            provider=provider.name,
            model=getattr(provider, "model", "?"),
            duration_ms=0,
            success=False,
            cost_usd=0.0,
            error_class=type(exc).__name__,
            error_message=str(exc)[:1000],
            request_meta={
                "document_id": str(document_id),
                "chunk_count": len(chunks),
                "contextual_retrieval": CONTEXTUAL_RETRIEVAL_VERSION,
            },
        )
        raise

    _log_embed_call(cur, job, metrics, document_id, len(chunks))

    if len(vectors) != len(chunks):
        raise RuntimeError(
            f"embedding provider returned {len(vectors)} vectors for {len(chunks)} chunks"
        )

    # Clear any pre-existing chunks for an idempotent re-ingest. The partial
    # UNIQUE protects against intra-batch dupes; this protects against drift
    # if the source document was edited and re-uploaded with the same id.
    delete_existing_chunks(cur, document_id=document_id, tenant_id=tenant_id)

    inserted = 0
    for chunk, vector, retrieval_text in zip(chunks, vectors, retrieval_texts):
        if insert_chunk(
            cur,
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            retrieval_text=retrieval_text,
            token_count=chunk.token_count,
            embedding=vector,
            content_hash=chunk.content_hash,
            heading_path=chunk.heading_path,
            source_page=chunk.source_page,
            source_locator=chunk.source_locator,
        ):
            inserted += 1

    update_document_status(
        cur, document_id=document_id, tenant_id=tenant_id, status="ready"
    )
    log.info(
        "document_embedded",
        document_id=str(document_id),
        chunks_total=len(chunks),
        chunks_inserted=inserted,
        provider=metrics.provider,
        model=metrics.model,
        input_tokens=metrics.input_tokens,
        cost_usd=metrics.cost_usd,
    )
    return {
        "chunks": inserted,
        "ready": True,
        "provider": metrics.provider,
        "model": metrics.model,
        "input_tokens": metrics.input_tokens,
        "cost_usd": metrics.cost_usd,
    }


def _log_embed_call(
    cur, job: dict[str, Any], metrics: CallMetrics, document_id: Any, chunk_count: int
) -> None:
    # This is deliberately durable: once the provider returns, the tenant may
    # have been billed even if downstream chunk inserts or status updates fail.
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
            "document_id": str(document_id),
            "chunk_count": chunk_count,
            "contextual_retrieval": CONTEXTUAL_RETRIEVAL_VERSION,
        },
    )


def _fail_document(
    cur,
    *,
    document_id: Any,
    tenant_id: str,
    job_id: Any,
    parse_error: str,
) -> None:
    update_document_status(
        cur,
        document_id=document_id,
        tenant_id=tenant_id,
        status="failed",
        parse_error=parse_error,
    )
    log_model_call_isolated(
        tenant_id=tenant_id,
        job_id=job_id,
        kind="embedding",
        provider="parse",
        model="none",
        duration_ms=0,
        success=False,
        cost_usd=0.0,
        error_class="parse_error",
        error_message=parse_error[:1000],
        request_meta={"document_id": str(document_id)},
    )
    log.warning(
        "document_parse_failed",
        document_id=str(document_id),
        tenant_id=tenant_id,
        parse_error=parse_error,
    )
