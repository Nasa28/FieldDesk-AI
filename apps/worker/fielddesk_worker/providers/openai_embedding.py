from __future__ import annotations

import time
from typing import Any

import httpx

from fielddesk_worker.providers.base import CallMetrics


PROVIDER_NAME = "openai"
DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_DIMS = 1536

# Pricing per 1M tokens, USD. As of mid-2026 these are the published rates;
# refresh from the OpenAI pricing page when they change rather than guessing.
COST_PER_1M_INPUT_USD: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}

# OpenAI embeddings endpoint limit: 2048 inputs and 300k tokens per request.
# We batch under both — picking a conservative ceiling on inputs so a single
# bad input doesn't fail the whole batch and tank an entire document.
DEFAULT_BATCH_SIZE = 96


class OpenAIEmbeddingProvider:
    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 60.0,
        batch_size: int = DEFAULT_BATCH_SIZE,
        dimensions: int = DEFAULT_DIMS,
    ):
        if not api_key:
            raise ValueError("OpenAI api_key is required")
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._batch_size = batch_size
        self._dimensions = dimensions

    @property
    def model(self) -> str:
        return self._model

    def embed(
        self, texts: list[str], model: str | None = None
    ) -> tuple[list[list[float]], CallMetrics]:
        """Embed a list of texts; returns (vectors, aggregated metrics).

        Batches across the OpenAI endpoint limit. Cost / duration / token
        counts aggregate across all batches into a single CallMetrics so the
        caller logs one ai_model_calls row per logical embed() invocation
        (matching how the Whisper / extraction providers report their cost).
        """
        effective_model = model or self._model
        if not texts:
            return [], CallMetrics(
                provider=PROVIDER_NAME, model=effective_model, success=True
            )

        url = f"{self._base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        vectors: list[list[float]] = []
        total_input_tokens = 0
        started = time.perf_counter()

        with httpx.Client(timeout=self._timeout) as client:
            for batch in _chunked(texts, self._batch_size):
                payload: dict[str, Any] = {
                    "input": batch,
                    "model": effective_model,
                }
                if effective_model.startswith("text-embedding-3-"):
                    payload["dimensions"] = self._dimensions
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
                # OpenAI returns data sorted by `index`; defensively sort anyway
                # — a future minor format change should not silently scramble
                # vectors against their input texts.
                data = sorted(body["data"], key=lambda d: d["index"])
                batch_vectors = [d["embedding"] for d in data]
                bad_dims = [len(v) for v in batch_vectors if len(v) != self._dimensions]
                if bad_dims:
                    raise RuntimeError(
                        f"embedding provider returned dimensions {bad_dims[0]}, "
                        f"expected {self._dimensions}"
                    )
                vectors.extend(batch_vectors)
                usage = body.get("usage", {})
                total_input_tokens += int(usage.get("prompt_tokens", 0))

        duration_ms = int((time.perf_counter() - started) * 1000)
        cost_per_1m = COST_PER_1M_INPUT_USD.get(effective_model, 0.0)
        cost_usd = (total_input_tokens / 1_000_000.0) * cost_per_1m
        metrics = CallMetrics(
            provider=PROVIDER_NAME,
            model=effective_model,
            input_tokens=total_input_tokens,
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            success=True,
        )
        return vectors, metrics


def _chunked(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
