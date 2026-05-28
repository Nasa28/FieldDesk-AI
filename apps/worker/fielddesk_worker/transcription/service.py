from __future__ import annotations

import time
from typing import Any

from fielddesk_worker.config import load_settings
from fielddesk_worker.db_queries import (
    enqueue_job,
    get_voice_note_for_update,
    insert_model_call,
    insert_transcript,
    log_model_call_isolated,
    update_voice_note_status,
)
from fielddesk_worker.providers.base import TranscriptionProvider
from fielddesk_worker.storage import ObjectInfo, get_object_bytes, stat_object


def _make_provider() -> TranscriptionProvider:
    s = load_settings()
    name = (s.transcription_provider or "stub").lower()
    if name == "stub":
        from fielddesk_worker.providers.stub import StubTranscriptionProvider

        return StubTranscriptionProvider()
    if name == "openai":
        if not s.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required when TRANSCRIPTION_PROVIDER=openai"
            )
        from fielddesk_worker.providers.openai import OpenAITranscriptionProvider

        return OpenAITranscriptionProvider(api_key=s.openai_api_key, model=s.transcription_model)
    raise ValueError(f"unknown TRANSCRIPTION_PROVIDER: {s.transcription_provider!r}")


def _expected_provider_name() -> str:
    s = load_settings()
    return (s.transcription_provider or "stub").lower()


def _expected_model_name() -> str:
    s = load_settings()
    name = _expected_provider_name()
    if name == "stub":
        from fielddesk_worker.providers.stub import DEFAULT_MODEL as STUB_DEFAULT

        return STUB_DEFAULT
    return s.transcription_model


def _normalize_content_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _expected_size(payload: dict[str, Any], voice_note: dict[str, Any]) -> int | None:
    value = payload.get("size_bytes")
    if value is None:
        value = voice_note.get("size_bytes")
    if value is None:
        return None
    return int(value)


def _validate_object_info(
    info: ObjectInfo,
    *,
    object_key: str,
    expected_size: int | None,
    expected_content_type: str,
    expected_etag: str | None,
) -> None:
    if not info.exists:
        raise FileNotFoundError(f"object not found in storage: {object_key}")
    if expected_size is not None and info.size != expected_size:
        raise ValueError(
            f"object size {info.size} does not match expected size {expected_size}"
        )
    got_type = _normalize_content_type(info.content_type)
    want_type = _normalize_content_type(expected_content_type)
    if got_type and want_type and got_type != want_type:
        raise ValueError(
            f"object content type {got_type!r} does not match expected {want_type!r}"
        )
    got_etag = (info.etag or "").strip('"')
    want_etag = (expected_etag or "").strip('"')
    if got_etag and want_etag and got_etag != want_etag:
        raise ValueError("object etag changed after upload confirmation")


def transcribe(job: dict[str, Any], cur) -> dict[str, Any]:
    payload = job.get("payload") or {}
    voice_note_id = payload["voice_note_id"]
    tenant_id = str(job["tenant_id"])
    payload_tenant_id = payload.get("tenant_id")
    if payload_tenant_id and str(payload_tenant_id) != tenant_id:
        raise ValueError("job payload tenant_id does not match job tenant_id")

    voice_note = get_voice_note_for_update(cur, voice_note_id=voice_note_id, tenant_id=tenant_id)
    object_key = voice_note["object_key"]
    mime_type = voice_note["mime_type"] or "application/octet-stream"
    if payload.get("object_key") and payload["object_key"] != object_key:
        raise ValueError("job payload object_key does not match voice note object_key")
    expected_size = _expected_size(payload, voice_note)
    expected_etag = payload.get("etag")

    provider = _make_provider()

    update_voice_note_status(
        cur,
        voice_note_id=voice_note_id,
        tenant_id=tenant_id,
        status="transcribing",
        expected_status="uploaded",
    )

    before = stat_object(object_key)
    _validate_object_info(
        before,
        object_key=object_key,
        expected_size=expected_size,
        expected_content_type=mime_type,
        expected_etag=expected_etag,
    )
    audio_bytes = get_object_bytes(object_key)
    if expected_size is not None and len(audio_bytes) != expected_size:
        raise ValueError(
            f"downloaded object size {len(audio_bytes)} does not match expected size {expected_size}"
        )
    after = stat_object(object_key)
    _validate_object_info(
        after,
        object_key=object_key,
        expected_size=expected_size,
        expected_content_type=mime_type,
        expected_etag=expected_etag or before.etag,
    )

    started = time.perf_counter()
    try:
        result = provider.transcribe(audio_bytes, mime_type)
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        log_model_call_isolated(
            tenant_id=tenant_id,
            job_id=job["id"],
            kind="transcription",
            provider=_expected_provider_name(),
            model=_expected_model_name(),
            duration_ms=elapsed_ms,
            success=False,
            cost_usd=0.0,
            error_class=type(exc).__name__,
            error_message=str(exc),
            request_meta={
                "voice_note_id": voice_note_id,
                "object_key": object_key,
                "bytes": len(audio_bytes),
                "mime_type": mime_type,
            },
        )
        raise

    transcript_id = insert_transcript(
        cur,
        tenant_id=tenant_id,
        voice_note_id=voice_note_id,
        text=result.text,
        provider=result.provider,
        model=result.model,
        duration_ms=result.duration_ms,
        cost_usd=result.cost_usd,
        language=result.language,
    )

    insert_model_call(
        cur,
        tenant_id=tenant_id,
        job_id=job["id"],
        kind="transcription",
        provider=result.provider,
        model=result.model,
        duration_ms=result.duration_ms,
        cost_usd=result.cost_usd,
        success=True,
        request_meta={
            "voice_note_id": voice_note_id,
            "object_key": object_key,
            "bytes": len(audio_bytes),
            "mime_type": mime_type,
            **(result.metadata or {}),
        },
    )

    update_voice_note_status(
        cur,
        voice_note_id=voice_note_id,
        tenant_id=tenant_id,
        status="transcribed",
        expected_status="transcribing",
    )

    next_job_id = enqueue_job(
        cur,
        tenant_id=tenant_id,
        type_="extract",
        payload={
            "tenant_id": tenant_id,
            "voice_note_id": voice_note_id,
            "transcript_id": str(transcript_id),
        },
        idempotency_key=f"voice-note:{voice_note_id}:extract",
        max_attempts=load_settings().max_retries,
    )

    return {
        "transcript_id": str(transcript_id),
        "voice_note_id": voice_note_id,
        "next_job_id": str(next_job_id),
        "provider": result.provider,
        "model": result.model,
        "duration_ms": result.duration_ms,
        "cost_usd": result.cost_usd,
        "language": result.language,
    }
