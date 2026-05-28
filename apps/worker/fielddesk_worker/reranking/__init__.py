"""Optional rerank pass between hybrid_search and the consumer.

The standard two-stage retrieval pattern: fetch more candidates than we
need from the cheap channel (RRF-fused dense + lexical) and then ask a
relevance-tuned model to reorder them. The reranker doesn't see the
document store; it scores the candidates we already retrieved, and we
keep the top-K of its ordering.

Pluggability mirrors EXTRACTION_PROVIDER / LLM_PROVIDER / EMBEDDING_PROVIDER:
RERANK_PROVIDER selects the implementation. The 'none' provider is a
pass-through so the rest of the pipeline doesn't need an "if reranking
enabled" branch — every caller goes through rerank.rerank(...) and gets
the right behavior.
"""

from fielddesk_worker.reranking.base import RerankedHit, Reranker, RerankerMetrics
from fielddesk_worker.reranking.service import make_reranker

__all__ = ["RerankedHit", "Reranker", "RerankerMetrics", "make_reranker"]
