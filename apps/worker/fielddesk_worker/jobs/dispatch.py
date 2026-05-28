from __future__ import annotations

from typing import Any

import structlog

from fielddesk_worker.jobs import JobType

log = structlog.get_logger()


def handle_job(job: dict[str, Any], cur) -> dict[str, Any]:
    job_type = JobType(job["type"])
    log.info("job_dispatch", id=str(job.get("id")), type=job_type)

    if job_type is JobType.TRANSCRIBE:
        from fielddesk_worker.transcription.service import transcribe

        return transcribe(job, cur)
    if job_type is JobType.EXTRACT:
        from fielddesk_worker.extraction.service import extract

        return extract(job, cur)
    if job_type is JobType.EMBED:
        from fielddesk_worker.embeddings.service import embed

        return embed(job, cur)
    if job_type is JobType.RAG:
        from fielddesk_worker.rag.service import retrieve

        return retrieve(job, cur)
    if job_type is JobType.DRAFT_TICKET:
        from fielddesk_worker.extraction.service import draft_ticket

        return draft_ticket(job, cur)

    raise ValueError(f"unknown job type: {job_type}")
