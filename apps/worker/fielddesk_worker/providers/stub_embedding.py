from __future__ import annotations

import hashlib
import math
import struct

from fielddesk_worker.providers.base import CallMetrics


PROVIDER_NAME = "stub"
DEFAULT_MODEL = "stub-embedding-v1"
DEFAULT_DIMS = 1536


class StubEmbeddingProvider:
    """Deterministic, hash-derived embeddings for tests and offline dev.

    Why deterministic: tests need to assert "same text → same embedding" and
    "different text → different embedding" without spending a real $0.0001
    per token. The vectors are not semantically meaningful — they just satisfy
    the contract (correct dim, unit norm, deterministic) so the rest of the
    pipeline (insert, similarity search) can be exercised end-to-end.
    """

    name = PROVIDER_NAME

    def __init__(self, *, model: str = DEFAULT_MODEL, dims: int = DEFAULT_DIMS):
        if dims <= 0:
            raise ValueError("dims must be positive")
        self._model = model
        self._dims = dims

    @property
    def model(self) -> str:
        return self._model

    def embed(
        self, texts: list[str], model: str | None = None
    ) -> tuple[list[list[float]], CallMetrics]:
        effective_model = model or self._model
        vectors = [self._vector_for(t) for t in texts]
        return vectors, CallMetrics(
            provider=PROVIDER_NAME,
            model=effective_model,
            input_tokens=sum(len(t) // 4 for t in texts),
            duration_ms=0,
            cost_usd=0.0,
            success=True,
        )

    def _vector_for(self, text: str) -> list[float]:
        # Expand a SHA-256 digest into self._dims doubles by repeated hashing,
        # then unit-normalize. Keeps the vector stable across runs of the same
        # text without needing the input length to drive dimensionality.
        out: list[float] = []
        counter = 0
        while len(out) < self._dims:
            digest = hashlib.sha256(f"{text}:{counter}".encode("utf-8")).digest()
            # 32 bytes = 8 floats per hash round.
            for i in range(0, 32, 4):
                if len(out) >= self._dims:
                    break
                n = struct.unpack_from(">I", digest, i)[0]
                # Map uint32 to [-1, 1].
                out.append((n / 2**31) - 1.0)
            counter += 1
        norm = math.sqrt(sum(x * x for x in out)) or 1.0
        return [x / norm for x in out]
