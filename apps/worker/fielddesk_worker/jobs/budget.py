"""Worker-side budget pre-flight for paid AI jobs.

Split out from queue.py so the pre-flight has a stable test seam and queue.py
stays under the file-size soft cap. The actual block writes (UPDATE on
ai_jobs + INSERT on human_reviews) live in jobs.reliability.mark_budget_blocked
because they share the LostLeaseError handling pattern with other terminal-state
transitions; this module is just the read + dispatch shell.

Two distinct gates run here:
  * Daily/monthly tenant cap (always evaluated for budget-gated job types).
  * Per-ticket cost cap (only evaluated for jobs whose payload carries a
    ticket_id at pickup time — rag, draft_ticket). PRD §12.

The per-ticket gate fires AFTER the tenant gate. If the tenant cap already
blocked the job, we don't run the per-ticket query — saves a round-trip and
gives the tenant cap visual precedence in the failures feed when both apply.
"""

from __future__ import annotations

from typing import Any

import structlog
from psycopg.rows import dict_row

from fielddesk_worker.db import conn
from fielddesk_worker.db_queries.ai_model_calls import read_ticket_spend
from fielddesk_worker.db_queries.tenant_budgets import BudgetUsage, read_budget_usage
from fielddesk_worker.jobs.reliability import (
    WORKER_ID,
    LostLeaseError,
    is_budget_gated_job,
    is_per_ticket_gated_job,
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


def ticket_block_detail(spend: float, cap: float, ticket_id: str) -> str:
    """Mirror of block_detail for the per-ticket cap. Includes the ticket id
    so an operator skimming the failures feed can correlate without opening
    the row."""
    return (
        f"cost_cap_exceeded: ticket {ticket_id} "
        f"${spend:.4f} >= ${cap:.2f}"
    )


def is_blocked(
    job: dict[str, Any], payload: dict[str, Any], attempt_number: int
) -> bool:
    """Run both pre-flights; return True if the job was routed to review.

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
                    if usage is None:
                        return False
                    if usage.should_block():
                        _route_to_review(
                            cur, job, payload, attempt_number,
                            reason="budget_exceeded",
                            detail=block_detail(usage),
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
                    if _per_ticket_block(cur, job, payload, attempt_number, usage):
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


def _per_ticket_block(
    cur,
    job: dict[str, Any],
    payload: dict[str, Any],
    attempt_number: int,
    usage: BudgetUsage,
) -> bool:
    """Return True if the per-ticket cap tripped and we routed to review.

    Skips when any precondition is missing rather than reading and discarding
    the result — read_ticket_spend hits the DB, no point if the answer
    can't change anything. Matches the tenant-gate posture: pause_on_exceeded
    is the kill switch; if it's off, the cap is just informational.
    """
    if not is_per_ticket_gated_job(str(job["type"])):
        return False
    if usage.max_cost_per_ticket is None or not usage.pause_on_exceeded:
        return False
    ticket_id = payload.get("ticket_id")
    if not ticket_id:
        return False
    spend = read_ticket_spend(
        cur, tenant_id=job["tenant_id"], ticket_id=str(ticket_id)
    )
    if spend < float(usage.max_cost_per_ticket):
        return False
    detail = ticket_block_detail(spend, float(usage.max_cost_per_ticket), str(ticket_id))
    _route_to_review(
        cur, job, payload, attempt_number,
        reason="cost_cap_exceeded",
        detail=detail,
    )
    log.warning(
        "job_ticket_cost_blocked",
        id=str(job["id"]),
        type=job["type"],
        tenant_id=str(job["tenant_id"]),
        ticket_id=str(ticket_id),
        ticket_spend_usd=spend,
        max_cost_per_ticket=float(usage.max_cost_per_ticket),
    )
    return True


def _route_to_review(
    cur,
    job: dict[str, Any],
    payload: dict[str, Any],
    attempt_number: int,
    *,
    reason: str,
    detail: str,
) -> None:
    """Thin wrapper over mark_budget_blocked so the two gates share one
    write path. Centralizes the WORKER_ID arg so a future change (e.g.
    per-worker IDs) only touches one line."""
    mark_budget_blocked(
        cur, job, payload, attempt_number, WORKER_ID, detail, reason=reason,
    )
