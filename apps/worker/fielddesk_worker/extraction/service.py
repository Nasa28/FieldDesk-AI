from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from fielddesk_worker.config import load_settings
from fielddesk_worker.db_queries import (
    enqueue_job,
    get_transcript,
    insert_ai_extraction,
    insert_human_review,
    insert_job_ticket_from_extraction,
    insert_model_call,
    link_extraction_to_ticket,
    log_model_call_isolated,
)
from fielddesk_worker.extraction.schema import TicketExtraction
from fielddesk_worker.prompts import (
    DEFAULT_EXTRACTION_PROMPT_VERSION,
    extraction_prompt_hash,
)
from fielddesk_worker.providers.base import ExtractionResult, LLMExtractionProvider


PROMPT_VERSION = DEFAULT_EXTRACTION_PROMPT_VERSION
PROMPT_HASH = extraction_prompt_hash(PROMPT_VERSION)
SCHEMA_VERSION = "ticket.v1"


def _make_provider() -> LLMExtractionProvider:
    s = load_settings()
    name = (s.extraction_provider or "stub").lower()
    if name == "stub":
        from fielddesk_worker.providers.extraction_stub import StubLLMExtractionProvider

        return StubLLMExtractionProvider()
    if name == "openai":
        if not s.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required when EXTRACTION_PROVIDER=openai"
            )
        from fielddesk_worker.providers.openai_llm import OpenAIExtractionProvider

        return OpenAIExtractionProvider(api_key=s.openai_api_key, model=s.extraction_model)
    raise ValueError(f"unknown EXTRACTION_PROVIDER: {s.extraction_provider!r}")


def _expected_provider_name() -> str:
    s = load_settings()
    return (s.extraction_provider or "stub").lower()


def _expected_model_name() -> str:
    s = load_settings()
    if _expected_provider_name() == "stub":
        from fielddesk_worker.providers.extraction_stub import DEFAULT_MODEL as STUB_DEFAULT

        return STUB_DEFAULT
    return s.extraction_model


def _decide_review(
    *, validated: TicketExtraction | None, validation_error: str | None, threshold: float
) -> tuple[bool, str | None]:
    if validation_error is not None or validated is None:
        return True, "invalid_json"
    if validated.human_review_required:
        return True, "provider_uncertainty"
    if validated.confidence < threshold:
        return True, "low_confidence"
    if not validated.issue_summary:
        return True, "missing_fields"
    return False, None


def extract(job: dict[str, Any], cur) -> dict[str, Any]:
    payload = job.get("payload") or {}
    tenant_id = str(job["tenant_id"])
    payload_tenant_id = payload.get("tenant_id")
    if payload_tenant_id and str(payload_tenant_id) != tenant_id:
        raise ValueError("job payload tenant_id does not match job tenant_id")

    voice_note_id = payload["voice_note_id"]
    transcript_id = payload["transcript_id"]

    transcript = get_transcript(cur, transcript_id=transcript_id, tenant_id=tenant_id)
    transcript_text = transcript["text"] or ""

    provider = _make_provider()

    started = time.perf_counter()
    try:
        result: ExtractionResult = provider.extract_ticket(
            transcript_text,
            {"voice_note_id": voice_note_id, "transcript_id": transcript_id},
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        log_model_call_isolated(
            tenant_id=tenant_id,
            job_id=job["id"],
            kind="llm",
            provider=_expected_provider_name(),
            model=_expected_model_name(),
            duration_ms=elapsed_ms,
            success=False,
            cost_usd=0.0,
            error_class=type(exc).__name__,
            error_message=str(exc),
            request_meta={
                "transcript_id": transcript_id,
                "voice_note_id": voice_note_id,
                "prompt_version": PROMPT_VERSION,
                "prompt_hash": PROMPT_HASH,
                "schema_version": SCHEMA_VERSION,
            },
        )
        raise

    validated: TicketExtraction | None = None
    validation_error: str | None = None
    try:
        validated = TicketExtraction.model_validate(result.parsed_json)
    except ValidationError as exc:
        validation_error = str(exc)

    settings = load_settings()
    needs_review, review_reason = _decide_review(
        validated=validated,
        validation_error=validation_error,
        threshold=settings.extraction_confidence_threshold,
    )

    parsed_output_jsonable: dict[str, Any] | None = (
        validated.model_dump(mode="json") if validated is not None else None
    )
    json_valid = validation_error is None
    confidence_value = (
        validated.confidence if validated is not None else result.confidence
    )

    extraction_id = insert_ai_extraction(
        cur,
        tenant_id=tenant_id,
        transcript_id=transcript_id,
        provider=result.provider,
        model=result.model,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        raw_output={"text": result.raw_text, "parsed": result.parsed_json},
        parsed_output=parsed_output_jsonable,
        json_valid=json_valid,
        confidence=confidence_value,
        cost_usd=result.cost_usd,
        duration_ms=result.duration_ms,
        error_message=validation_error,
    )

    insert_model_call(
        cur,
        tenant_id=tenant_id,
        job_id=job["id"],
        kind="llm",
        provider=result.provider,
        model=result.model,
        duration_ms=result.duration_ms,
        success=True,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        request_meta={
            "transcript_id": transcript_id,
            "voice_note_id": voice_note_id,
            "transcript_chars": len(transcript_text),
            "prompt_version": PROMPT_VERSION,
            "prompt_hash": PROMPT_HASH,
            "schema_version": SCHEMA_VERSION,
        },
        response_meta={
            "json_valid": json_valid,
            "confidence": confidence_value,
            "human_review_required": needs_review,
            "review_reason": review_reason,
            **(result.metadata or {}),
        },
    )

    job_ticket_id: str | None = None
    human_review_id: str | None = None

    if not needs_review and validated is not None:
        job_ticket_id = insert_job_ticket_from_extraction(
            cur,
            tenant_id=tenant_id,
            voice_note_id=voice_note_id,
            transcript_id=transcript_id,
            fields=parsed_output_jsonable or {},
        )
        link_extraction_to_ticket(
            cur,
            extraction_id=extraction_id,
            tenant_id=tenant_id,
            job_ticket_id=job_ticket_id,
        )
        # Auto-enqueue a RAG retrieval so the ticket page can show "Related
        # documents" without a second human action. Idempotency key includes
        # the ticket id so re-running extraction (e.g. after a re-resolve)
        # coalesces onto the same rag job rather than spawning duplicates.
        enqueue_job(
            cur,
            tenant_id=tenant_id,
            type_="rag",
            payload={"ticket_id": job_ticket_id, "top_k": 5, "source": "auto"},
            idempotency_key=f"rag:ticket:{job_ticket_id}",
        )
    else:
        human_review_id = insert_human_review(
            cur,
            tenant_id=tenant_id,
            ai_job_id=job["id"],
            voice_note_id=voice_note_id,
            transcript_id=transcript_id,
            ai_extraction_id=extraction_id,
            reason=review_reason or "other",
            notes=validation_error,
        )

    return {
        "extraction_id": str(extraction_id),
        "job_ticket_id": job_ticket_id,
        "human_review_id": human_review_id,
        "json_valid": json_valid,
        "confidence": confidence_value,
        "human_review_required": needs_review,
        "review_reason": review_reason,
        "provider": result.provider,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
    }


def draft_ticket(job: dict[str, Any], cur) -> dict[str, Any]:
    return {"stub": True, "job_id": str(job.get("id"))}
