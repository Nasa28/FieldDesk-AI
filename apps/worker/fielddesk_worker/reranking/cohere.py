from __future__ import annotations

import time

import httpx

from fielddesk_worker.reranking.base import RerankedHit, RerankerMetrics


# Cohere prices rerank-v3.5 at $2.00 per 1,000 "search units." One search
# unit = one call with up to 100 documents. A rerank call with > 100
# documents gets billed as multiple units. We trust the response's
# meta.billed_units.search_units for the actual count so the cost row
# matches what the invoice will say.
_COST_PER_SEARCH_UNIT_USD = 0.002

_COHERE_RERANK_URL = "https://api.cohere.com/v2/rerank"
_DEFAULT_TIMEOUT_SECONDS = 30.0


class CohereReranker:
    """Cohere Rerank v3.5 client.

    The API itself is a single POST. Most of this class is "translate
    Cohere's response into the local RerankedHit + RerankerMetrics shape
    so the calling pipeline doesn't need to know about Cohere quirks."
    """

    name = "cohere"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "rerank-v3.5",
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ):
        if not api_key:
            raise ValueError("CohereReranker requires a non-empty api_key")
        self._api_key = api_key
        self.model = model
        self._timeout_seconds = timeout_seconds

    def is_noop(self) -> bool:
        return False

    def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> tuple[list[RerankedHit], RerankerMetrics]:
        if not documents:
            return [], RerankerMetrics(
                provider=self.name,
                model=self.model,
                duration_ms=0,
                success=True,
                cost_usd=0.0,
                candidate_count=0,
            )

        body = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": min(top_n, len(documents)),
            # We already have the document text on the caller side; asking
            # Cohere to echo it back doubles the response payload.
            "return_documents": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        try:
            response = httpx.post(
                _COHERE_RERANK_URL,
                json=body,
                headers=headers,
                timeout=self._timeout_seconds,
            )
        except httpx.RequestError as exc:
            return [], RerankerMetrics(
                provider=self.name,
                model=self.model,
                duration_ms=int((time.perf_counter() - started) * 1000),
                success=False,
                cost_usd=0.0,
                candidate_count=len(documents),
                error_class=type(exc).__name__,
                error_message=str(exc)[:1000],
            )
        duration_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code != 200:
            return [], RerankerMetrics(
                provider=self.name,
                model=self.model,
                duration_ms=duration_ms,
                success=False,
                cost_usd=0.0,
                candidate_count=len(documents),
                error_class=f"http_{response.status_code}",
                error_message=response.text[:1000],
            )

        try:
            payload = response.json()
            hits = [
                RerankedHit(
                    index=int(item["index"]),
                    relevance_score=float(item["relevance_score"]),
                )
                for item in payload.get("results", [])
            ]
            # Cohere returns billed_units in meta. Default to 1 search unit
            # when missing so we don't under-report cost in the rare case
            # the field is absent (older API versions or partial responses).
            billed_units = (
                payload.get("meta", {}).get("billed_units", {}).get("search_units")
                or 1
            )
        except Exception as exc:  # noqa: BLE001
            return [], RerankerMetrics(
                provider=self.name,
                model=self.model,
                duration_ms=duration_ms,
                success=False,
                cost_usd=0.0,
                candidate_count=len(documents),
                error_class=type(exc).__name__,
                error_message=str(exc)[:1000],
            )
        cost_usd = float(billed_units) * _COST_PER_SEARCH_UNIT_USD
        return hits, RerankerMetrics(
            provider=self.name,
            model=self.model,
            duration_ms=duration_ms,
            success=True,
            cost_usd=cost_usd,
            candidate_count=len(documents),
            extra={"billed_search_units": billed_units},
        )
