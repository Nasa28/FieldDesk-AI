"""Provider protocols.

Each provider is a small interface so the worker can swap implementations
without touching service logic. Cost and token accounting is the caller's
responsibility — every call must log to `ai_model_calls`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class CallMetrics:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    cost_usd: float = 0.0
    success: bool = True
    error_class: str | None = None


class TranscriptionProvider(Protocol):
    name: str

    def transcribe(self, audio_bytes: bytes, mime: str) -> tuple[str, CallMetrics]: ...


class LLMProvider(Protocol):
    name: str

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict,
        model: str,
    ) -> tuple[dict, CallMetrics]: ...


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, texts: list[str], model: str) -> tuple[list[list[float]], CallMetrics]: ...
