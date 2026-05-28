from __future__ import annotations

from fielddesk_worker.providers.base import TranscriptionResult


PROVIDER_NAME = "stub"
DEFAULT_MODEL = "stub-transcriber-v1"

FAKE_TRANSCRIPT = (
    "[stub transcript] Customer called about a leaking water heater in the "
    "basement. Wants someone out tomorrow morning. Mentioned a 5-year warranty."
)


class StubTranscriptionProvider:
    def __init__(self, model: str = DEFAULT_MODEL):
        self._model = model

    def transcribe(self, audio_bytes: bytes, mime_type: str) -> TranscriptionResult:
        return TranscriptionResult(
            text=FAKE_TRANSCRIPT,
            provider=PROVIDER_NAME,
            model=self._model,
            duration_ms=0,
            cost_usd=0.0,
            language=None,
            metadata={"bytes": len(audio_bytes), "mime_type": mime_type},
        )
