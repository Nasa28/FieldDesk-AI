from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from fielddesk_worker.db_queries._helpers import returned_id


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
    return returned_id(cur.fetchone())


def link_extraction_to_ticket(
    cur,
    *,
    extraction_id: str | UUID,
    tenant_id: str | UUID,
    job_ticket_id: str | UUID,
) -> None:
    cur.execute(
        """
        UPDATE ai_extractions
        SET job_ticket_id = %s
        WHERE id = %s AND tenant_id = %s
        """,
        (job_ticket_id, extraction_id, tenant_id),
    )
    if cur.rowcount != 1:
        raise ValueError("extraction not found for tenant")
