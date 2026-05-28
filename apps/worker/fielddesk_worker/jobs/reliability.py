from __future__ import annotations

import os
import socket
import threading
from uuid import uuid4

import structlog

from fielddesk_worker.config import load_settings
from fielddesk_worker.db import conn

log = structlog.get_logger()
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"


class LostLeaseError(RuntimeError):
    pass


def _heartbeat_job(
    job_id: str,
    tenant_id: str,
    worker_id: str,
    lease_seconds: int,
    interval_seconds: int,
    stop: threading.Event,
) -> None:
    while not stop.wait(interval_seconds):
        try:
            with conn() as c:
                with c.transaction():
                    with c.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE ai_jobs
                            SET lease_expires_at = now() + (%s || ' seconds')::interval,
                                updated_at = now()
                            WHERE id = %s
                              AND tenant_id = %s
                              AND locked_by = %s
                              AND status = 'processing'
                            """,
                            (str(lease_seconds), job_id, tenant_id, worker_id),
                        )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "job_heartbeat_failed",
                id=str(job_id),
                worker_id=worker_id,
                error_class=type(exc).__name__,
                error_message=str(exc),
            )


def start_heartbeat(
    job_id: str, tenant_id: str, worker_id: str
) -> tuple[threading.Event, threading.Thread]:
    settings = load_settings()
    lease_seconds = max(30, int(settings.job_lease_seconds))
    configured_interval = max(1, int(settings.job_heartbeat_seconds))
    interval_seconds = min(configured_interval, max(1, lease_seconds // 3))
    stop = threading.Event()
    thread = threading.Thread(
        target=_heartbeat_job,
        args=(job_id, tenant_id, worker_id, lease_seconds, interval_seconds, stop),
        daemon=True,
    )
    thread.start()
    return stop, thread


def is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, (FileNotFoundError, KeyError, ValueError)):
        return False
    if isinstance(exc, RuntimeError) and "required when" in str(exc):
        return False
    return True


def is_reviewable_job(job_type: str) -> bool:
    return job_type in {"transcribe", "extract", "embed", "rag", "draft_ticket"}


# Jobs whose handlers will call a paid AI provider. Post-Phase-4.5,
# draft_ticket is the RAG-synthesis LLM call (not the no-op stub it used to
# be), so it joins the gated set — letting it run past a budget cap would
# spend real money on recs that nobody will see if the rest of the queue
# is blocked anyway.
BUDGET_GATED_JOB_TYPES = frozenset({"transcribe", "extract", "embed", "rag", "draft_ticket"})


def is_budget_gated_job(job_type: str) -> bool:
    return job_type in BUDGET_GATED_JOB_TYPES


def mark_budget_blocked(
    cur,
    job: dict[str, object],
    payload: dict[str, object],
    attempt_number: int,
    worker_id: str,
    detail: str,
) -> None:
    """Route a budget-blocked job to human review without calling its handler.

    Why a separate function (not raising into the normal failure path): going
    through retry/backoff for a budget cap would burn retry budget pointlessly
    — the cap won't lift on its own. We mark the job needs_review immediately,
    record an attempt audit row, surface it in the unified failure feed, and
    create a human_reviews row so the operator sees *why* the job stopped.
    """
    cur.execute(
        """
        UPDATE ai_jobs
        SET status = 'needs_review',
            finished_at = now(),
            updated_at = now(),
            error_class = 'budget_exceeded',
            error_message = %s,
            locked_by = NULL,
            lease_expires_at = NULL
        WHERE id = %s
          AND tenant_id = %s
          AND locked_by = %s
          AND status = 'processing'
        """,
        (detail, job["id"], job["tenant_id"], worker_id),
    )
    if cur.rowcount != 1:
        raise LostLeaseError(
            f"job lease lost before budget-block update: {job['id']}"
        )
    cur.execute(
        """
        INSERT INTO ai_job_attempts
            (job_id, attempt_number, status, error_class, error_message,
             duration_ms, started_at, finished_at)
        VALUES (%s, %s, 'failed', 'budget_exceeded', %s, 0, now(), now())
        """,
        (job["id"], attempt_number, detail),
    )
    cur.execute(
        """
        INSERT INTO human_reviews
            (tenant_id, ai_job_id, voice_note_id, transcript_id, reason, notes)
        SELECT %s, %s, %s, %s, 'budget_exceeded', %s
        WHERE NOT EXISTS (
            SELECT 1 FROM human_reviews
            WHERE tenant_id = %s
              AND ai_job_id = %s
              AND status = 'open'
        )
        """,
        (
            job["tenant_id"],
            job["id"],
            payload.get("voice_note_id"),
            payload.get("transcript_id"),
            detail,
            job["tenant_id"],
            job["id"],
        ),
    )


def insert_failure_review(
    cur, job: dict[str, object], payload: dict[str, object], err_class: str, err_msg: str
) -> None:
    if not is_reviewable_job(str(job["type"])):
        return
    cur.execute(
        """
        INSERT INTO human_reviews
            (tenant_id, job_ticket_id, ai_job_id, voice_note_id,
             transcript_id, reason, notes)
        SELECT %s, %s, %s, %s, %s, 'fallback', %s
        WHERE NOT EXISTS (
            SELECT 1 FROM human_reviews
            WHERE tenant_id = %s
              AND ai_job_id = %s
              AND status = 'open'
        )
        """,
        (
            job["tenant_id"],
            payload.get("ticket_id"),
            job["id"],
            payload.get("voice_note_id"),
            payload.get("transcript_id"),
            f"{err_class}: {err_msg}",
            job["tenant_id"],
            job["id"],
        ),
    )
