from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from typing import Any

import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

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

log = structlog.get_logger()


def _claim_one(cur, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    cur.execute(
        """
        UPDATE ai_jobs
        SET status = 'processing',
            started_at = now(),
            attempt_count = attempt_count + 1,
            locked_by = %s,
            lease_expires_at = now() + (%s || ' seconds')::interval,
            updated_at = now()
        WHERE id = (
            SELECT id FROM ai_jobs
            WHERE (
                status IN ('pending', 'retrying')
                AND run_after <= now()
            ) OR (
                status = 'processing'
                AND (
                    lease_expires_at < now()
                    OR (
                        lease_expires_at IS NULL
                        AND updated_at < now() - interval '15 minutes'
                    )
                )
            )
            ORDER BY run_after, updated_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING id, tenant_id, type, status, payload, idempotency_key,
                  attempt_count, max_attempts, locked_by, lease_expires_at
        """,
        (worker_id, str(lease_seconds)),
    )
    return cur.fetchone()


def _record_attempt(
    cur,
    job_id: str,
    attempt_number: int,
    status: str,
    started_at: datetime,
    duration_ms: int,
    error_class: str | None = None,
    error_message: str | None = None,
) -> None:
    cur.execute(
        """
        INSERT INTO ai_job_attempts
            (job_id, attempt_number, status, error_class, error_message,
             duration_ms, started_at, finished_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, now())
        """,
        (job_id, attempt_number, status, error_class, error_message, duration_ms, started_at),
    )


def _mark_succeeded(
    cur, job_id: str, tenant_id: str, worker_id: str, result: dict[str, Any]
) -> None:
    cur.execute(
        """
        UPDATE ai_jobs
        SET status = 'succeeded',
            finished_at = now(),
            updated_at = now(),
            result = %s,
            locked_by = NULL,
            lease_expires_at = NULL
        WHERE id = %s
          AND tenant_id = %s
          AND locked_by = %s
          AND status = 'processing'
        """,
        (Jsonb(result), job_id, tenant_id, worker_id),
    )
    if cur.rowcount != 1:
        raise LostLeaseError(f"job lease lost before success update: {job_id}")


def _mark_failed_or_retry(
    cur,
    job_id: str,
    tenant_id: str,
    worker_id: str,
    attempt_count: int,
    max_attempts: int,
    retryable: bool,
    reviewable: bool,
    err_class: str,
    err_msg: str,
) -> str:
    if not retryable or attempt_count >= max_attempts:
        final_status = "needs_review" if reviewable else "failed"
        cur.execute(
            """
            UPDATE ai_jobs
            SET status = %s,
                finished_at = now(),
                updated_at = now(),
                error_class = %s,
                error_message = %s,
                locked_by = NULL,
                lease_expires_at = NULL
            WHERE id = %s
              AND tenant_id = %s
              AND locked_by = %s
              AND status = 'processing'
            """,
            (final_status, err_class, err_msg, job_id, tenant_id, worker_id),
        )
        if cur.rowcount != 1:
            raise LostLeaseError(f"job lease lost before final failure update: {job_id}")
        return final_status

    # Exponential backoff with small jitter, capped at 5min.
    delay_seconds = min(5 * (2 ** (attempt_count - 1)) + random.uniform(0, 5), 300)
    cur.execute(
        """
        UPDATE ai_jobs
        SET status = 'retrying',
            updated_at = now(),
            error_class = %s,
            error_message = %s,
            run_after = now() + (%s || ' seconds')::interval,
            locked_by = NULL,
            lease_expires_at = NULL
        WHERE id = %s
          AND tenant_id = %s
          AND locked_by = %s
          AND status = 'processing'
        """,
        (err_class, err_msg, str(delay_seconds), job_id, tenant_id, worker_id),
    )
    if cur.rowcount != 1:
        raise LostLeaseError(f"job lease lost before retry update: {job_id}")
    return "retrying"


def _decode_payload(job: dict[str, Any]) -> dict[str, Any]:
    payload = job["payload"] or {}
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    return payload


def _claim_next_job(worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    with conn() as c:
        c.row_factory = dict_row
        with c.transaction():
            with c.cursor() as cur:
                return _claim_one(cur, worker_id, lease_seconds)


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
    payload = _decode_payload(job)
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
                    _record_attempt(
                        cur, job_id, attempt_number, "succeeded", started_at, duration_ms
                    )
                    _mark_succeeded(cur, job_id, tenant_id, WORKER_ID, result)
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
                        _record_attempt(
                            cur,
                            job_id,
                            attempt_number,
                            "failed",
                            started_at,
                            duration_ms,
                            error_class=err_class,
                            error_message=err_msg,
                        )
                        final_status = _mark_failed_or_retry(
                            cur,
                            job_id,
                            tenant_id,
                            WORKER_ID,
                            attempt_number,
                            job["max_attempts"],
                            retryable,
                            reviewable,
                            err_class,
                            err_msg,
                        )
                        if (
                            final_status in {"failed", "needs_review"}
                            and job["type"] == "transcribe"
                        ):
                            _mark_voice_note_failed_transcription(cur, job, payload, err_class)
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


def _mark_voice_note_failed_transcription(
    cur, job: dict[str, Any], payload: dict[str, Any], error_class: str
) -> None:
    vn_id = payload.get("voice_note_id")
    tenant_id = job.get("tenant_id")
    if not vn_id or not tenant_id:
        return
    cur.execute(
        """
        UPDATE voice_notes
        SET status = 'failed',
            error_class = %s,
            updated_at = now()
        WHERE id = %s AND tenant_id = %s
          AND status IN ('uploaded', 'transcribing')
        """,
        (error_class, vn_id, tenant_id),
    )
