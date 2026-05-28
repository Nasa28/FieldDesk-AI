from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


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


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    provider: str
    model: str
    duration_ms: int
    cost_usd: float
    language: str | None = None
    raw_response: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractionResult:
    raw_text: str
    parsed_json: dict[str, Any]
    provider: str
    model: str
    duration_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class TranscriptionProvider(Protocol):
    def transcribe(self, audio_bytes: bytes, mime_type: str) -> TranscriptionResult: ...


class LLMExtractionProvider(Protocol):
    def extract_ticket(
        self, transcript_text: str, context: dict[str, Any]
    ) -> ExtractionResult: ...


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
