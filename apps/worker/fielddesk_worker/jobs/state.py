"""SQL helpers for ai_jobs lifecycle transitions.

Extracted from queue.py so the orchestrator (process_one) stays under the
file-size soft cap and is readable as a single page. Each helper here takes
a cursor and performs exactly one state change against ai_jobs (or its
related rows in voice_notes / documents). They raise LostLeaseError when an
UPDATE doesn't hit the expected row — that's the signal that another
worker grabbed the lease (e.g. after a network blip).
"""

from __future__ import annotations

import json
import random
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from fielddesk_worker.jobs.reliability import LostLeaseError


def claim_one(cur, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    """Atomically claim the oldest eligible job: pending/retrying that's ready
    to run, OR processing-but-lease-expired (recover-stuck-jobs path).
    Uses FOR UPDATE SKIP LOCKED so concurrent workers don't grab the same row.
    """
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


def record_attempt(
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


def mark_succeeded(
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


def mark_failed_or_retry(
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
    """Decide between terminal failure (needs_review | failed) and retrying.

    Terminal: when the exception isn't retryable OR we've exhausted attempts.
    `reviewable` maps job_type → whether a human queue is the right
    destination for exhausted failures.
    """
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

    # Exponential backoff with small jitter, capped at 5min. Jitter prevents
    # synchronized retry storms across the worker pool when a provider blips.
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


def decode_payload(job: dict[str, Any]) -> dict[str, Any]:
    payload = job["payload"] or {}
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    return payload


def mark_voice_note_failed_transcription(
    cur, job: dict[str, Any], payload: dict[str, Any], error_class: str
) -> None:
    """Mirror the job's terminal failure into the voice_notes row so the UI
    can show "transcription failed" without joining against ai_jobs."""
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


def mark_document_failed_embedding(
    cur, job: dict[str, Any], payload: dict[str, Any], error_class: str, error_message: str
) -> None:
    """Mirror the job's terminal failure into the documents row, with the
    error_message preserved as parse_error so the Documents page can show
    *why* an embed failed (e.g. 'encrypted PDFs are not supported in v1')."""
    document_id = payload.get("document_id")
    tenant_id = job.get("tenant_id")
    if not document_id or not tenant_id:
        return
    detail = f"{error_class}: {error_message}"[:2000]
    cur.execute(
        """
        UPDATE documents
        SET status = 'failed',
            parse_error = %s,
            updated_at = now()
        WHERE id = %s AND tenant_id = %s
          AND status IN ('pending', 'processing')
        """,
        (detail, document_id, tenant_id),
    )
