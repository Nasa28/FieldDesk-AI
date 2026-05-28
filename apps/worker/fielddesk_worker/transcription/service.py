"""Transcription service.

For Phase 1, step 1, this returns a deterministic fake transcript so the
queue path can be exercised end-to-end without calling any external provider.

TODO: replace with a real transcription provider (Whisper API / faster-whisper).
The real implementation must:
  1. Stream audio from object storage by ``object_key``.
  2. Reject empty audio / unsupported mime up front (non-retryable).
  3. Call the provider with a per-call timeout, capturing latency.
  4. Insert into ``transcripts`` and log an ``ai_model_calls`` row with
     provider, model, tokens, duration_ms, cost_usd, and success.
  5. Update ``voice_notes.status`` to ``transcribed`` (or ``failed``).
  6. Enqueue the downstream ``extract`` job.
"""

from __future__ import annotations

from typing import Any


FAKE_TRANSCRIPT = (
    "[stub transcript] Customer called about a leaking water heater in the "
    "basement. Wants someone out tomorrow morning. Mentioned a 5-year warranty."
)


def transcribe(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("payload") or {}
    voice_note_id = payload.get("voice_note_id")
    return {
        "stub": True,
        "voice_note_id": voice_note_id,
        "object_key": payload.get("object_key"),
        "transcript_text": FAKE_TRANSCRIPT,
        "provider": "stub",
        "model": "stub-v0",
        "duration_ms": 0,
        "cost_usd": 0.0,
    }
