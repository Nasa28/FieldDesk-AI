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

    # Exponential backoff: 5s, 10s, 20s, ... capped at 5min.
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


def _decode_payload(job: dict[str, Any]) -> dict[str, Any]:
    payload = job["payload"] or {}
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    return payload


def _claim_next_job() -> dict[str, Any] | None:
    with conn() as c:
        c.row_factory = dict_row
        with c.transaction():
            with c.cursor() as cur:
                return _claim_one(cur)


def process_one() -> int:
    job = _claim_next_job()
    if job is None:
        return 0

    job_id = job["id"]
    attempt_number = job["attempt_count"]
    started_at = datetime.now(tz=timezone.utc)
    payload = _decode_payload(job)
    log.info("job_claimed", id=str(job_id), type=job["type"], attempt=attempt_number)

    try:
        with conn() as c:
            c.row_factory = dict_row
            with c.transaction():
                with c.cursor() as cur:
                    result = handle_job({**job, "payload": payload}, cur)
                    duration_ms = int(
                        (datetime.now(tz=timezone.utc) - started_at).total_seconds() * 1000
                    )
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
        with conn() as c:
            c.row_factory = dict_row
            with c.transaction():
                with c.cursor() as cur:
                    _record_attempt(
                        cur, job_id, attempt_number, "failed", started_at, duration_ms,
                        error_class=err_class, error_message=err_msg,
                    )
                    final_status = _mark_failed_or_retry(
                        cur, job_id, attempt_number, job["max_attempts"], err_class, err_msg
                    )
                    if final_status == "failed" and job["type"] == "transcribe":
                        _mark_voice_note_failed_transcription(cur, job, payload, err_class)
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
        """,
        (error_class, vn_id, tenant_id),
    )
