from __future__ import annotations

from fielddesk_worker.config import load_settings
from fielddesk_worker.reranking.base import Reranker


def make_reranker() -> Reranker:
    """Pick the configured reranker.

    Returns NoopReranker when RERANK_PROVIDER is 'none' or unset so the
    rest of the pipeline can call rerank.rerank(...) unconditionally and
    rely on is_noop() to short-circuit the hybrid_search overrequest.
    """
    settings = load_settings()
    provider = (settings.rerank_provider or "none").strip().lower()
    if provider == "none":
        from fielddesk_worker.reranking.noop import NoopReranker

        return NoopReranker()
    if provider == "cohere":
        from fielddesk_worker.reranking.cohere import CohereReranker

        if not settings.cohere_api_key:
            raise RuntimeError(
                "RERANK_PROVIDER=cohere requires COHERE_API_KEY to be set"
            )
        # The default RERANK_MODEL ("rerank-v3.5") is Cohere's. If the
        # operator is using Voyage's default model name with Cohere
        # selected, fail fast rather than send a 400 to Cohere's API.
        model = settings.rerank_model
        if not model.startswith("rerank-v"):
            model = "rerank-v3.5"
        return CohereReranker(api_key=settings.cohere_api_key, model=model)
    if provider == "voyage":
        from fielddesk_worker.reranking.voyage import VoyageReranker

        if not settings.voyage_api_key:
            raise RuntimeError(
                "RERANK_PROVIDER=voyage requires VOYAGE_API_KEY to be set"
            )
        # rerank-2.5-lite is the cheapest Voyage option (25x cheaper than
        # Cohere per call). If the operator left RERANK_MODEL at Cohere's
        # default we silently map to Voyage's cheapest model rather than
        # send a 400.
        model = settings.rerank_model
        if not model.startswith("rerank-2"):
            model = "rerank-2.5-lite"
        return VoyageReranker(api_key=settings.voyage_api_key, model=model)
    raise RuntimeError(f"unsupported RERANK_PROVIDER: {provider!r}")
