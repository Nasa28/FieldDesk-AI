"""Dispatch a row from `ai_jobs` to the correct handler."""

from __future__ import annotations

from typing import Any

import structlog

from fielddesk_worker.jobs import JobType

log = structlog.get_logger()


def handle_job(job: dict[str, Any]) -> dict[str, Any]:
    """Route a job to its handler. Returns a result dict the caller will persist."""
    job_type = JobType(job["type"])
    log.info("job_dispatch", id=job.get("id"), type=job_type)

    if job_type is JobType.TRANSCRIBE:
        from fielddesk_worker.transcription.service import transcribe

        return transcribe(job)
    if job_type is JobType.EXTRACT:
        from fielddesk_worker.extraction.service import extract

        return extract(job)
    if job_type is JobType.EMBED:
        from fielddesk_worker.embeddings.service import embed

        return embed(job)
    if job_type is JobType.RAG:
        from fielddesk_worker.rag.service import retrieve

        return retrieve(job)
    if job_type is JobType.DRAFT_TICKET:
        from fielddesk_worker.extraction.service import draft_ticket

        return draft_ticket(job)

    raise ValueError(f"unknown job type: {job_type}")
