from __future__ import annotations

from typing import Any
from uuid import UUID


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


def update_voice_note_status(
    cur,
    *,
    voice_note_id: str | UUID,
    tenant_id: str | UUID,
    status: str,
    expected_status: str | None = None,
) -> None:
    cur.execute(
        """
        UPDATE voice_notes
        SET status = %s, updated_at = now()
        WHERE id = %s AND tenant_id = %s
          AND (%s::text IS NULL OR status = %s)
        """,
        (status, voice_note_id, tenant_id, expected_status, expected_status),
    )
    if cur.rowcount != 1:
        raise ValueError("voice note not found for tenant or invalid status")
