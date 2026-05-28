from __future__ import annotations

from fielddesk_worker.reranking.base import RerankedHit, RerankerMetrics


class NoopReranker:
    """Pass-through reranker. Returns the input ordering verbatim, with
    relevance_score = 1.0 / (rank + 1) so any downstream code that sorts
    by score still produces the original order.

    Used when RERANK_PROVIDER='none' (the default) so callers don't have
    to branch — everything goes through the same rerank helper and the
    noop short-circuits the overrequest path.
    """

    name = "none"
    model = "noop"

    def is_noop(self) -> bool:
        return True

    def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> tuple[list[RerankedHit], RerankerMetrics]:
        # `query` is intentionally unused — the noop reranker keeps the
        # input ordering. Naming it in the signature keeps the Protocol
        # contract obvious to readers.
        del query
        limit = min(top_n, len(documents))
        hits = [
            RerankedHit(index=i, relevance_score=1.0 / (i + 1))
            for i in range(limit)
        ]
        return hits, RerankerMetrics(
            provider=self.name,
            model=self.model,
            duration_ms=0,
            success=True,
            cost_usd=0.0,
            candidate_count=len(documents),
        )
