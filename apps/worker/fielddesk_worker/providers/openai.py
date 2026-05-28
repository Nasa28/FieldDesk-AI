from __future__ import annotations

import time

import httpx

from fielddesk_worker.providers.base import TranscriptionResult


PROVIDER_NAME = "openai"
DEFAULT_MODEL = "whisper-1"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

# whisper-1: $0.006 per minute. Other models priced differently; extend the table as needed.
COST_PER_SECOND_USD = {
    "whisper-1": 0.006 / 60.0,
}


_MIME_TO_EXT = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
}


def _extension_for(mime_type: str) -> str:
    return _MIME_TO_EXT.get(mime_type.lower(), "bin")


class OpenAITranscriptionProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 120.0,
    ):
        if not api_key:
            raise ValueError("OpenAI api_key is required")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def transcribe(self, audio_bytes: bytes, mime_type: str) -> TranscriptionResult:
        filename = f"audio.{_extension_for(mime_type)}"
        files = {"file": (filename, audio_bytes, mime_type)}
        data = {"model": self._model, "response_format": "verbose_json"}
        headers = {"Authorization": f"Bearer {self._api_key}"}

        url = f"{self._base_url}/audio/transcriptions"
        started = time.perf_counter()
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(url, files=files, data=data, headers=headers)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        r.raise_for_status()
        body = r.json()

        text = body.get("text", "")
        language = body.get("language")
        audio_duration_sec = float(body.get("duration") or 0.0)
        per_sec = COST_PER_SECOND_USD.get(
            self._model, max(COST_PER_SECOND_USD.values())
        )
        cost = round(audio_duration_sec * per_sec, 6)

        return TranscriptionResult(
            text=text,
            provider=PROVIDER_NAME,
            model=self._model,
            duration_ms=elapsed_ms,
            cost_usd=cost,
            language=language,
            raw_response=body,
            metadata={
                "audio_duration_sec": audio_duration_sec,
                "bytes": len(audio_bytes),
                "mime_type": mime_type,
            },
        )
