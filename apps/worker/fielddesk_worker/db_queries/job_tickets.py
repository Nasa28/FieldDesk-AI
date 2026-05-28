from __future__ import annotations

from typing import Any
from uuid import UUID

from fielddesk_worker.db_queries._helpers import returned_id


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
    return returned_id(cur.fetchone())
