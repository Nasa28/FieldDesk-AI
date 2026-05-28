from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RerankedHit:
    """One reranked candidate. `index` points back into the input list so
    the caller can stitch together its own metadata (chunk_id, document_title,
    source_locator) without the reranker needing to know those fields.
    `relevance_score` is provider-specific (Cohere returns 0..1 floats) and
    only meaningful relative to other scores in the same call.
    """

    index: int
    relevance_score: float


@dataclass(frozen=True)
class RerankerMetrics:
    """Provider-call metadata for one rerank invocation.

    Mirrors the shape of CallMetrics used elsewhere so the cost-logging
    helper in rag/service.py can write a uniform ai_model_calls row.
    Cohere prices per-query rather than per-token, so input_tokens stays
    0 and cost is computed by the caller from candidate count and unit
    price; the provider just reports duration + success.
    """

    provider: str
    model: str
    duration_ms: int
    success: bool
    cost_usd: float = 0.0
    candidate_count: int = 0
    error_class: str | None = None
    error_message: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Reranker(Protocol):
    """Pluggable reranker. Implementations must be deterministic-ish: given
    the same (query, documents) they should return the same ordering, so
    the eval can be reproduced and the cost dashboard isn't lying about
    "why did the recs change for the same ticket?"
    """

    name: str
    model: str

    def is_noop(self) -> bool:
        """True when this reranker passes input through unchanged. The
        caller can short-circuit hybrid_search overrequest in that case
        — there's no point fetching 20 candidates to keep 5.
        """
        ...

    def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> tuple[list[RerankedHit], RerankerMetrics]:
        """Score the candidates and return the top_n by relevance.

        `documents` is the list of chunk_text values in the order they
        came out of hybrid_search; the returned RerankedHit.index points
        back into that list. top_n is the final K the caller wants; the
        reranker should clamp to len(documents) if asked for more.
        """
        ...
