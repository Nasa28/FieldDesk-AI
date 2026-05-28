"""Worker-side budget pre-flight for paid AI jobs.

Split out from queue.py so the pre-flight has a stable test seam and queue.py
stays under the file-size soft cap. The actual block writes (UPDATE on
ai_jobs + INSERT on human_reviews) live in jobs.reliability.mark_budget_blocked
because they share the LostLeaseError handling pattern with other terminal-state
transitions; this module is just the read + dispatch shell.
"""

from __future__ import annotations

from typing import Any

import structlog
from psycopg.rows import dict_row

from fielddesk_worker.db import conn
from fielddesk_worker.db_queries.tenant_budgets import BudgetUsage, read_budget_usage
from fielddesk_worker.jobs.reliability import (
    WORKER_ID,
    LostLeaseError,
    is_budget_gated_job,
    mark_budget_blocked,
)

log = structlog.get_logger()


def block_detail(usage: BudgetUsage) -> str:
    """Human-readable summary of which cap tripped. Used as the job's
    error_message and the human_reviews note so an operator can see at a
    glance whether daily, monthly, or both fired."""
    parts: list[str] = []
    if usage.daily_over and usage.daily_budget_usd is not None:
        parts.append(
            f"daily ${usage.daily_spend_usd:.4f} >= ${usage.daily_budget_usd:.2f}"
        )
    if usage.monthly_over and usage.monthly_budget_usd is not None:
        parts.append(
            f"monthly ${usage.monthly_spend_usd:.4f} >= ${usage.monthly_budget_usd:.2f}"
        )
    return "budget_exceeded: " + "; ".join(parts) if parts else "budget_exceeded"


def is_blocked(
    job: dict[str, Any], payload: dict[str, Any], attempt_number: int
) -> bool:
    """Run the budget pre-flight; return True if the job was routed to review.

    True means the caller should skip handle_job entirely — no provider call,
    no spend, no lease to release (mark_budget_blocked already cleared it).
    False means the job is clear to proceed.
    """
    if not is_budget_gated_job(str(job["type"])):
        return False
    job_id = job["id"]
    try:
        with conn() as c:
            c.row_factory = dict_row
            with c.transaction():
                with c.cursor() as cur:
                    usage = read_budget_usage(cur, tenant_id=job["tenant_id"])
                    if usage is None or not usage.should_block():
                        return False
                    detail = block_detail(usage)
                    mark_budget_blocked(
                        cur, job, payload, attempt_number, WORKER_ID, detail
                    )
                    log.warning(
                        "job_budget_blocked",
                        id=str(job_id),
                        type=job["type"],
                        tenant_id=str(job["tenant_id"]),
                        daily_over=usage.daily_over,
                        monthly_over=usage.monthly_over,
                        daily_spend_usd=usage.daily_spend_usd,
                        monthly_spend_usd=usage.monthly_spend_usd,
                    )
                    return True
    except LostLeaseError as lease_exc:
        log.warning(
            "job_lease_lost",
            id=str(job_id),
            type=job["type"],
            attempt=attempt_number,
            error_message=str(lease_exc),
        )
        return True
    return False
