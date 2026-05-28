from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fielddesk_worker.config import load_settings
from fielddesk_worker.db import conn
from fielddesk_worker.db_queries._helpers import log, returned_id


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
    return returned_id(cur.fetchone())


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
