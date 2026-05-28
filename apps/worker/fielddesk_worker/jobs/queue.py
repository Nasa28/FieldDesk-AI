"""Postgres-backed job queue.

Pulls one job at a time using ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple
workers can run safely against the same table. Every job lifecycle event
(claim, succeed, fail) is wrapped in a single transaction with the matching
``ai_job_attempts`` row, so the attempt log and the job row never disagree.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fielddesk_worker.db import conn
from fielddesk_worker.jobs.dispatch import handle_job

log = structlog.get_logger()


def _claim_one(cur) -> dict[str, Any] | None:
    cur.execute(
        """
        UPDATE ai_jobs
        SET status = 'processing',
            started_at = COALESCE(started_at, now()),
            attempt_count = attempt_count + 1,
            updated_at = now()
        WHERE id = (
            SELECT id FROM ai_jobs
            WHERE status IN ('pending', 'retrying')
              AND run_after <= now()
            ORDER BY run_after
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING id, tenant_id, type, status, payload, idempotency_key,
                  attempt_count, max_attempts
        """
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


def _mark_succeeded(cur, job_id: str, result: dict[str, Any]) -> None:
    cur.execute(
        """
        UPDATE ai_jobs
        SET status = 'succeeded',
            finished_at = now(),
            updated_at = now(),
            result = %s
        WHERE id = %s
        """,
        (Jsonb(result), job_id),
    )


def _mark_failed_or_retry(
    cur, job_id: str, attempt_count: int, max_attempts: int, err_class: str, err_msg: str
) -> str:
    """Decide between scheduling another retry and giving up."""
    if attempt_count >= max_attempts:
        cur.execute(
            """
            UPDATE ai_jobs
            SET status = 'failed',
                finished_at = now(),
                updated_at = now(),
                error_class = %s,
                error_message = %s
            WHERE id = %s
            """,
            (err_class, err_msg, job_id),
        )
        return "failed"

    # Exponential backoff with a cap. base=5s, factor=2, max=5min.
    delay_seconds = min(5 * (2 ** (attempt_count - 1)), 300)
    cur.execute(
        """
        UPDATE ai_jobs
        SET status = 'retrying',
            updated_at = now(),
            error_class = %s,
            error_message = %s,
            run_after = now() + (%s || ' seconds')::interval
        WHERE id = %s
        """,
        (err_class, err_msg, str(delay_seconds), job_id),
    )
    return "retrying"


def process_one() -> int:
    """Claim and process one job. Returns 1 if a job was handled, 0 otherwise."""
    with conn() as c:
        c.row_factory = dict_row
        with c.transaction():
            with c.cursor() as cur:
                job = _claim_one(cur)
                if job is None:
                    return 0

                job_id = job["id"]
                attempt_number = job["attempt_count"]
                started_at = datetime.now(tz=timezone.utc)
                log.info("job_claimed", id=str(job_id), type=job["type"], attempt=attempt_number)

                # Normalize payload: psycopg returns dict for jsonb already.
                payload = job["payload"] or {}
                if isinstance(payload, (str, bytes)):
                    payload = json.loads(payload)

                try:
                    result = handle_job({**job, "payload": payload})
                    duration_ms = int((datetime.now(tz=timezone.utc) - started_at).total_seconds() * 1000)
                    _record_attempt(cur, job_id, attempt_number, "succeeded", started_at, duration_ms)
                    _mark_succeeded(cur, job_id, result)
                    log.info(
                        "job_succeeded",
                        id=str(job_id),
                        type=job["type"],
                        duration_ms=duration_ms,
                    )
                except Exception as exc:  # noqa: BLE001
                    duration_ms = int((datetime.now(tz=timezone.utc) - started_at).total_seconds() * 1000)
                    err_class = type(exc).__name__
                    err_msg = str(exc)
                    _record_attempt(
                        cur, job_id, attempt_number, "failed", started_at, duration_ms,
                        error_class=err_class, error_message=err_msg,
                    )
                    final_status = _mark_failed_or_retry(
                        cur, job_id, attempt_number, job["max_attempts"], err_class, err_msg
                    )
                    log.error(
                        "job_failed",
                        id=str(job_id),
                        type=job["type"],
                        attempt=attempt_number,
                        final_status=final_status,
                        error_class=err_class,
                        error_message=err_msg,
                    )
    return 1
