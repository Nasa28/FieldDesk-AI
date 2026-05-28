"""Worker queue orchestrator.

`process_one` is the loop body: claim a job, run the budget pre-flight,
dispatch it, then mark succeeded / retrying / needs_review. The SQL helpers
that actually transition `ai_jobs` rows live in `jobs/state.py`; the
budget pre-flight lives in `jobs/budget.py`. Keeping orchestration here
and SQL there makes process_one short enough to read top-to-bottom.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from psycopg.rows import dict_row

from fielddesk_worker.config import load_settings
from fielddesk_worker.db import conn
from fielddesk_worker.jobs.budget import is_blocked as is_budget_blocked
from fielddesk_worker.jobs.dispatch import handle_job
from fielddesk_worker.jobs.reliability import (
    WORKER_ID,
    LostLeaseError,
    insert_failure_review,
    is_retryable_exception,
    is_reviewable_job,
    start_heartbeat,
)
from fielddesk_worker.jobs.state import (
    claim_one,
    decode_payload,
    mark_document_failed_embedding,
    mark_failed_or_retry,
    mark_succeeded,
    mark_voice_note_failed_transcription,
    record_attempt,
)

log = structlog.get_logger()


def _claim_next_job(worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    with conn() as c:
        c.row_factory = dict_row
        with c.transaction():
            with c.cursor() as cur:
                return claim_one(cur, worker_id, lease_seconds)


def process_one() -> int:
    settings = load_settings()
    lease_seconds = max(30, int(settings.job_lease_seconds))
    job = _claim_next_job(WORKER_ID, lease_seconds)
    if job is None:
        return 0

    job_id = job["id"]
    tenant_id = str(job["tenant_id"])
    attempt_number = job["attempt_count"]
    started_at = datetime.now(tz=timezone.utc)
    payload = decode_payload(job)
    log.info("job_claimed", id=str(job_id), type=job["type"], attempt=attempt_number)

    heartbeat_stop, heartbeat_thread = start_heartbeat(
        str(job_id), tenant_id, WORKER_ID
    )

    try:
        if is_budget_blocked(job, payload, attempt_number):
            return 1

        with conn() as c:
            c.row_factory = dict_row
            with c.transaction():
                with c.cursor() as cur:
                    result = handle_job({**job, "payload": payload}, cur)
                    duration_ms = int(
                        (datetime.now(tz=timezone.utc) - started_at).total_seconds() * 1000
                    )
                    record_attempt(
                        cur, job_id, attempt_number, "succeeded", started_at, duration_ms
                    )
                    mark_succeeded(cur, job_id, tenant_id, WORKER_ID, result)
        log.info(
            "job_succeeded",
            id=str(job_id),
            type=job["type"],
            duration_ms=duration_ms,
        )
    except LostLeaseError as exc:
        log.warning(
            "job_lease_lost",
            id=str(job_id),
            type=job["type"],
            attempt=attempt_number,
            error_message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        duration_ms = int(
            (datetime.now(tz=timezone.utc) - started_at).total_seconds() * 1000
        )
        err_class = type(exc).__name__
        err_msg = str(exc)
        retryable = is_retryable_exception(exc)
        reviewable = is_reviewable_job(str(job["type"]))
        try:
            with conn() as c:
                c.row_factory = dict_row
                with c.transaction():
                    with c.cursor() as cur:
                        record_attempt(
                            cur, job_id, attempt_number, "failed", started_at, duration_ms,
                            error_class=err_class, error_message=err_msg,
                        )
                        final_status = mark_failed_or_retry(
                            cur, job_id, tenant_id, WORKER_ID, attempt_number,
                            job["max_attempts"], retryable, reviewable, err_class, err_msg,
                        )
                        if final_status in {"failed", "needs_review"}:
                            if job["type"] == "transcribe":
                                mark_voice_note_failed_transcription(cur, job, payload, err_class)
                            elif job["type"] == "embed":
                                mark_document_failed_embedding(
                                    cur, job, payload, err_class, err_msg
                                )
                        if final_status == "needs_review":
                            insert_failure_review(cur, job, payload, err_class, err_msg)
        except LostLeaseError as lease_exc:
            log.warning(
                "job_lease_lost",
                id=str(job_id),
                type=job["type"],
                attempt=attempt_number,
                error_message=str(lease_exc),
            )
            return 1
        log.error(
            "job_failed",
            id=str(job_id),
            type=job["type"],
            attempt=attempt_number,
            final_status=final_status,
            retryable=retryable,
            error_class=err_class,
            error_message=err_msg,
        )
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=2)
    return 1
