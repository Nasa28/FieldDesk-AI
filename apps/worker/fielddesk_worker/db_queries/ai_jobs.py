from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from fielddesk_worker.db_queries._helpers import returned_id


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
    return returned_id(cur.fetchone())
