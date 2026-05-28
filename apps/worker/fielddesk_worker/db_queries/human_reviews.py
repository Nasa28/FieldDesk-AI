from __future__ import annotations

from uuid import UUID

from fielddesk_worker.db_queries._helpers import returned_id


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
    return returned_id(cur.fetchone())
