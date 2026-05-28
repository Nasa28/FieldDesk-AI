from __future__ import annotations

import time

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from fielddesk_worker.reranking.base import RerankedHit, RerankerMetrics


# Voyage rerank-2.5-lite is $0.02 / 1M tokens (rerank-2.5 is $0.05 /1M).
# Total tokens billed = (query_tokens * num_documents) + sum(document_tokens).
# Voyage returns usage.total_tokens in the response, so we trust that
# number for cost rather than recomputing it client-side — the invoice
# will use whatever Voyage's tokenizer counts.
_COST_PER_MILLION_TOKENS_USD: dict[str, float] = {
    "rerank-2.5-lite": 0.02,
    "rerank-2.5":      0.05,
    "rerank-2-lite":   0.02,
    "rerank-2":        0.05,
}
_DEFAULT_COST_PER_MILLION_USD = 0.05  # unknown model → assume full rate

_VOYAGE_RERANK_URL = "https://api.voyageai.com/v1/rerank"
_DEFAULT_TIMEOUT_SECONDS = 30.0

# Voyage's free tier without a payment method on file is 3 RPM. The
# eval suite fires 12 rerank calls in ~15 seconds, which trips 429 on
# 9 of them. Exponential backoff (4s, 8s, 16s; max 4 attempts) covers
# one full rate-limit window — at ~20s/req under 3 RPM, we'll fit 3 of
# the retries into the next minute. Production accounts with a payment
# method on file have much higher limits and rarely hit this path.
_MAX_RETRY_ATTEMPTS = 4
_RETRY_WAIT_INITIAL_SEC = 4
_RETRY_WAIT_MAX_SEC = 32


class _RateLimitedRetry(Exception):
    """Marker that the Voyage API returned 429 and is retriable. Raised
    inside the _post_with_retry helper so tenacity picks it up; the outer
    rerank() catches it after the final attempt fails and surfaces the
    failure as RerankerMetrics(success=False) — same shape as every other
    failure path.
    """


class VoyageReranker:
    """Voyage AI rerank client. Same shape as the Cohere reranker — only
    the URL, request body, and response parsing differ.

    Voyage bills per-token rather than per-call, which makes the dogfood
    eval roughly 25x cheaper than Cohere for our typical query size. The
    free tier (200M tokens per account) covers years of dogfood + casual
    production use.
    """

    name = "voyage"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "rerank-2.5-lite",
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ):
        if not api_key:
            raise ValueError("VoyageReranker requires a non-empty api_key")
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
            "query": query,
            "documents": documents,
            "model": self.model,
            "top_k": min(top_n, len(documents)),
            # Saves response payload; we already have the documents.
            "return_documents": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        try:
            response = self._post_with_retry(body=body, headers=headers)
        except _RateLimitedRetry as exc:
            # Tenacity exhausted retries on 429s. Treat the same as any
            # other non-200 — caller falls back to hybrid_search ordering.
            return [], RerankerMetrics(
                provider=self.name,
                model=self.model,
                duration_ms=int((time.perf_counter() - started) * 1000),
                success=False,
                cost_usd=0.0,
                candidate_count=len(documents),
                error_class="http_429",
                error_message=str(exc)[:1000],
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
                for item in payload.get("data", [])
            ]
            total_tokens = int(payload.get("usage", {}).get("total_tokens") or 0)
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
        price_per_million = _COST_PER_MILLION_TOKENS_USD.get(
            self.model, _DEFAULT_COST_PER_MILLION_USD
        )
        cost_usd = total_tokens * price_per_million / 1_000_000.0
        return hits, RerankerMetrics(
            provider=self.name,
            model=self.model,
            duration_ms=duration_ms,
            success=True,
            cost_usd=cost_usd,
            candidate_count=len(documents),
            extra={"billed_tokens": total_tokens},
        )

    @retry(
        retry=retry_if_exception_type(_RateLimitedRetry),
        stop=stop_after_attempt(_MAX_RETRY_ATTEMPTS),
        wait=wait_exponential(
            multiplier=_RETRY_WAIT_INITIAL_SEC, max=_RETRY_WAIT_MAX_SEC
        ),
        reraise=True,
    )
    def _post_with_retry(self, *, body: dict, headers: dict) -> httpx.Response:
        """POST to Voyage with tenacity-driven retry on 429.

        Only HTTP 429 (rate-limit) triggers a retry — every other failure
        (RequestError, non-200, parse failure) is handled by the caller
        as a terminal RerankerMetrics(success=False). Voyage occasionally
        returns 429 even on paid accounts during burst traffic; the retry
        loop is cheap insurance for production, and on the free tier
        (3 RPM until a card is on file) it's the difference between the
        eval working and silently degrading to hybrid_search ordering.
        """
        response = httpx.post(
            _VOYAGE_RERANK_URL,
            json=body,
            headers=headers,
            timeout=self._timeout_seconds,
        )
        if response.status_code == 429:
            raise _RateLimitedRetry(response.text[:200])
        return response
