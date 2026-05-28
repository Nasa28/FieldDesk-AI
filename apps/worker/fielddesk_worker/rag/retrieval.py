"""Shared two-stage retrieval used by both the production RAG worker and
the eval runner. Keeps the rerank wiring in one place so changes don't
have to be mirrored across rag/service.py and evals/runner.py — if the
eval ever drifts from production, the recall@1 number stops being
trustworthy.

Stage 1: hybrid_search returns top-N candidates fused from dense (halfvec
cosine) + lexical (ts_rank_cd) channels via RRF. N is `top_k` when no
reranker is configured, or `rerank_overrequest` when one is.

Stage 2 (optional): the configured reranker scores the N candidates and
returns the top_k. Each candidate gets a `rerank_score` field added so
the rag_queries row + the UI can display it. We never write back
rerank_score to the originating chunk row — relevance is per-query, not
intrinsic to the chunk.
"""

from __future__ import annotations

from typing import Any

import structlog

from fielddesk_worker.config import load_settings
from fielddesk_worker.db_queries import hybrid_search
from fielddesk_worker.reranking import Reranker, RerankerMetrics, make_reranker

log = structlog.get_logger()

MAX_RERANK_CANDIDATES = 100


def retrieve_with_optional_rerank(
    cur,
    *,
    tenant_id: str,
    query_text: str,
    embedding_literal: str,
    top_k: int,
    reranker: Reranker | None = None,
) -> tuple[list[dict[str, Any]], RerankerMetrics | None]:
    """Run hybrid_search and, if a reranker is configured, rerank the
    overrequested candidates down to top_k.

    Returns (results, rerank_metrics_or_None). When reranking is disabled
    (or the reranker errors transparently), metrics is None and results
    are exactly what hybrid_search returned. When reranking succeeded,
    each result dict gains a `rerank_score` field.

    `reranker` is injectable for tests; production calls pass None and
    get whatever `make_reranker()` resolves from settings.
    """
    if reranker is None:
        reranker = make_reranker()

    final_top_k = max(1, min(int(top_k), MAX_RERANK_CANDIDATES))
    if reranker.is_noop():
        # Short-circuit: don't pay for an overrequest we'll just truncate
        # back to top_k. Saves a chunk of postgres work for the common
        # RERANK_PROVIDER=none deploys.
        results = hybrid_search(
            cur,
            tenant_id=tenant_id,
            embedding_literal=embedding_literal,
            query_text=query_text,
            top_k=final_top_k,
        )
        return list(results), None

    settings = load_settings()
    configured_overrequest = int(settings.rerank_overrequest or final_top_k)
    overrequest = min(
        max(final_top_k, configured_overrequest),
        MAX_RERANK_CANDIDATES,
    )
    candidates = hybrid_search(
        cur,
        tenant_id=tenant_id,
        embedding_literal=embedding_literal,
        query_text=query_text,
        top_k=overrequest,
    )
    if not candidates:
        return [], None
    candidate_list = list(candidates)

    # hybrid_search returns the chunk text under the SQL column `text`
    # (see f.text in apps/worker/fielddesk_worker/db_queries/rag.py).
    # An earlier draft read "chunk_text" here and silently fed the
    # reranker 20 empty strings, which made rerank a no-op regardless
    # of provider. Keep this key aligned with rag.py's SELECT.
    documents = [str(row.get("text") or "") for row in candidate_list]
    hits, metrics = reranker.rerank(
        query=query_text,
        documents=documents,
        top_n=final_top_k,
    )
    if not metrics.success:
        # Reranker failure: degrade gracefully to hybrid_search ordering
        # truncated to top_k. We still return the metrics so the caller
        # can log the failed rerank call (cost + error) to ai_model_calls.
        log.warning(
            "rerank_failed_falling_back_to_hybrid",
            provider=metrics.provider,
            error_class=metrics.error_class,
            error_message=metrics.error_message,
            candidate_count=metrics.candidate_count,
        )
        return candidate_list[:final_top_k], metrics

    reranked: list[dict[str, Any]] = []
    for hit in hits:
        if 0 <= hit.index < len(candidate_list):
            row = dict(candidate_list[hit.index])
            row["rerank_score"] = hit.relevance_score
            reranked.append(row)
    return reranked, metrics
