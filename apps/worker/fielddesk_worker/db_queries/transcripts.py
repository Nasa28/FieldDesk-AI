from __future__ import annotations

from typing import Any
from uuid import UUID

from fielddesk_worker.db_queries._helpers import returned_id


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
    return returned_id(cur.fetchone())


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
