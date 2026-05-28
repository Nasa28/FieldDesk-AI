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
        # Phase 4.5: draft_ticket is the RAG-synthesis step. The Phase-2 stub
        # in extraction/service.py is left for backward-compat tests only;
        # production dispatch goes through recommendations/service.synthesize.
        from fielddesk_worker.recommendations.service import synthesize

        return synthesize(job, cur)

    raise ValueError(f"unknown job type: {job_type}")
