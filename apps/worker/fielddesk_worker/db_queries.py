from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fielddesk_worker.config import load_settings
from fielddesk_worker.db import conn

log = structlog.get_logger()


def _returned_id(row: Any) -> str:
    if isinstance(row, dict):
        return row["id"]
    return row[0]


def get_voice_note_for_update(
    cur, *, voice_note_id: str | UUID, tenant_id: str | UUID
) -> dict[str, Any]:
    cur.execute(
        """
        SELECT id, tenant_id, object_key, mime_type, size_bytes, status
        FROM voice_notes
        WHERE id = %s AND tenant_id = %s
        FOR UPDATE
        """,
        (voice_note_id, tenant_id),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError("voice note not found for tenant")
    return dict(row)


def insert_transcript(
    cur,
    *,
    tenant_id: str | UUID,
    voice_note_id: str | UUID,
    text: str,
    provider: str,
    model: str,
    duration_ms: int,
    language: str | None = None,
    cost_usd: float = 0.0,
) -> str:
    cur.execute(
        """
        INSERT INTO transcripts
            (tenant_id, voice_note_id, text, language, provider, model, cost_usd, duration_ms)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (tenant_id, voice_note_id, text, language, provider, model, cost_usd, duration_ms),
    )
    return _returned_id(cur.fetchone())


def insert_model_call(
    cur,
    *,
    tenant_id: str | UUID,
    job_id: str | UUID | None,
    kind: str,
    provider: str,
    model: str,
    duration_ms: int,
    success: bool,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    error_class: str | None = None,
    error_message: str | None = None,
    request_meta: dict[str, Any] | None = None,
    response_meta: dict[str, Any] | None = None,
    durable: bool = True,
) -> str:
    if durable:
        with conn() as c:
            c.row_factory = dict_row
            with c.transaction():
                with c.cursor() as durable_cur:
                    return insert_model_call(
                        durable_cur,
                        tenant_id=tenant_id,
                        job_id=job_id,
                        kind=kind,
                        provider=provider,
                        model=model,
                        duration_ms=duration_ms,
                        success=success,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost_usd,
                        error_class=error_class,
                        error_message=error_message,
                        request_meta=request_meta,
                        response_meta=response_meta,
                        durable=False,
                    )

    cur.execute(
        """
        INSERT INTO ai_model_calls
            (tenant_id, job_id, kind, provider, model,
             input_tokens, output_tokens, duration_ms, cost_usd,
             success, error_class, error_message, request_meta, response_meta)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            tenant_id, job_id, kind, provider, model,
            input_tokens, output_tokens, duration_ms, cost_usd,
            success, error_class, error_message,
            Jsonb(request_meta or {}), Jsonb(response_meta or {}),
        ),
    )
    return _returned_id(cur.fetchone())


def update_voice_note_status(
    cur, *, voice_note_id: str | UUID, tenant_id: str | UUID, status: str
) -> None:
    cur.execute(
        """
        UPDATE voice_notes
        SET status = %s, updated_at = now()
        WHERE id = %s AND tenant_id = %s
        """,
        (status, voice_note_id, tenant_id),
    )


# Writes on a fresh, autocommitted connection so the row survives an outer
# savepoint rollback (used to log failed provider calls from a handler that
# is about to raise).
def log_model_call_isolated(
    *,
    tenant_id: str | UUID,
    job_id: str | UUID | None,
    kind: str,
    provider: str,
    model: str,
    duration_ms: int,
    success: bool,
    cost_usd: float = 0.0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error_class: str | None = None,
    error_message: str | None = None,
    request_meta: dict[str, Any] | None = None,
    response_meta: dict[str, Any] | None = None,
) -> None:
    s = load_settings()
    try:
        with psycopg.connect(s.database_url, autocommit=True) as c:
            with c.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_model_calls
                        (tenant_id, job_id, kind, provider, model,
                         input_tokens, output_tokens, duration_ms, cost_usd,
                         success, error_class, error_message,
                         request_meta, response_meta)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        tenant_id, job_id, kind, provider, model,
                        input_tokens, output_tokens, duration_ms, cost_usd,
                        success, error_class, error_message,
                        Jsonb(request_meta or {}), Jsonb(response_meta or {}),
                    ),
                )
    except Exception as exc:  # noqa: BLE001
        # Best-effort: never let bookkeeping mask the real provider error.
        log.warning("model_call_isolated_log_failed", error=str(exc))


def enqueue_job(
    cur,
    *,
    tenant_id: str | UUID,
    type_: str,
    payload: dict[str, Any],
    idempotency_key: str,
    max_attempts: int = 5,
) -> str:
    cur.execute(
        """
        INSERT INTO ai_jobs (tenant_id, type, payload, idempotency_key, max_attempts)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, idempotency_key) DO UPDATE
            SET updated_at = now()
        RETURNING id
        """,
        (tenant_id, type_, Jsonb(payload), idempotency_key, max_attempts),
    )
    return _returned_id(cur.fetchone())


def get_transcript(
    cur, *, transcript_id: str | UUID, tenant_id: str | UUID
) -> dict[str, Any]:
    cur.execute(
        """
        SELECT id, voice_note_id, text, language, provider, model
        FROM transcripts
        WHERE id = %s AND tenant_id = %s
        """,
        (transcript_id, tenant_id),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"transcript not found: {transcript_id}")
    return dict(row)


def insert_ai_extraction(
    cur,
    *,
    tenant_id: str | UUID,
    transcript_id: str | UUID,
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: str,
    raw_output: dict[str, Any],
    parsed_output: dict[str, Any] | None,
    json_valid: bool,
    confidence: float | None,
    cost_usd: float,
    duration_ms: int,
    error_message: str | None = None,
    job_ticket_id: str | UUID | None = None,
) -> str:
    cur.execute(
        """
        INSERT INTO ai_extractions
            (tenant_id, transcript_id, job_ticket_id,
             prompt_version, schema_version,
             raw_output, parsed_output, json_valid, confidence,
             provider, model, cost_usd, duration_ms, error_message)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            tenant_id, transcript_id, job_ticket_id,
            prompt_version, schema_version,
            Jsonb(raw_output),
            Jsonb(parsed_output) if parsed_output is not None else None,
            json_valid, confidence,
            provider, model, cost_usd, duration_ms, error_message,
        ),
    )
    return _returned_id(cur.fetchone())


def link_extraction_to_ticket(
    cur, *, extraction_id: str | UUID, job_ticket_id: str | UUID
) -> None:
    cur.execute(
        "UPDATE ai_extractions SET job_ticket_id = %s WHERE id = %s",
        (job_ticket_id, extraction_id),
    )


def insert_job_ticket_from_extraction(
    cur,
    *,
    tenant_id: str | UUID,
    voice_note_id: str | UUID,
    transcript_id: str | UUID,
    fields: dict[str, Any],
) -> str:
    cur.execute(
        """
        INSERT INTO job_tickets (
            tenant_id, voice_note_id, transcript_id,
            customer_name, customer_phone, service_address,
            trade_type, issue_summary, detailed_description,
            priority, preferred_visit_time,
            required_skills, suggested_parts, safety_concerns,
            warranty_mention, follow_up_questions,
            confidence, human_review_required,
            status, source
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s,
            'draft', 'ai_extraction'
        )
        RETURNING id
        """,
        (
            tenant_id, voice_note_id, transcript_id,
            fields.get("customer_name"), fields.get("customer_phone"), fields.get("service_address"),
            fields.get("trade_type"), fields.get("issue_summary"), fields.get("detailed_description"),
            fields.get("priority"), fields.get("preferred_visit_time"),
            list(fields.get("required_skills") or []),
            list(fields.get("suggested_parts") or []),
            list(fields.get("safety_concerns") or []),
            fields.get("warranty_mentioned"),
            list(fields.get("follow_up_questions") or []),
            fields.get("confidence"), bool(fields.get("human_review_required", False)),
        ),
    )
    return _returned_id(cur.fetchone())


def insert_human_review(
    cur,
    *,
    tenant_id: str | UUID,
    ai_job_id: str | UUID | None,
    reason: str,
    job_ticket_id: str | UUID | None = None,
    voice_note_id: str | UUID | None = None,
    transcript_id: str | UUID | None = None,
    ai_extraction_id: str | UUID | None = None,
    notes: str | None = None,
) -> str:
    cur.execute(
        """
        INSERT INTO human_reviews
            (tenant_id, job_ticket_id, ai_job_id,
             voice_note_id, transcript_id, ai_extraction_id,
             reason, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (tenant_id, job_ticket_id, ai_job_id,
         voice_note_id, transcript_id, ai_extraction_id,
         reason, notes),
    )
    return _returned_id(cur.fetchone())
