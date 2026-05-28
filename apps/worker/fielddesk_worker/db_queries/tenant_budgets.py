from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class BudgetUsage:
    """Mirror of v_tenant_budget_usage. NULL limits mean "no cap configured"
    and the corresponding *_over flag is always False."""

    tenant_id: str
    daily_budget_usd: float | None
    monthly_budget_usd: float | None
    max_cost_per_ticket: float | None
    pause_on_exceeded: bool
    daily_spend_usd: float
    monthly_spend_usd: float
    daily_over: bool
    monthly_over: bool

    def should_block(self) -> bool:
        """Pre-flight gate for new AI work.

        Why: we want to block before the provider call, not after, because a
        failed-after-charge call still costs money. The view computes
        daily_over / monthly_over as >= comparisons against the recorded spend
        in ai_model_calls; we OR them together because either cap exceeded is
        enough to pause.
        """
        return self.pause_on_exceeded and (self.daily_over or self.monthly_over)


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def read_budget_usage(cur, *, tenant_id: str | UUID) -> BudgetUsage | None:
    """Read the budget view for a tenant. Returns None when the tenant does
    not exist; a tenant with no budget row still returns a BudgetUsage with
    NULL limits and False over-flags."""
    cur.execute(
        """
        SELECT
            tenant_id,
            daily_budget_usd, monthly_budget_usd, max_cost_per_ticket,
            pause_on_exceeded,
            daily_spend_usd, monthly_spend_usd,
            daily_over, monthly_over
        FROM v_tenant_budget_usage
        WHERE tenant_id = %s
        """,
        (str(tenant_id),),
    )
    row = cur.fetchone()
    if row is None:
        return None
    if isinstance(row, dict):
        get = row.get
    else:
        keys = (
            "tenant_id",
            "daily_budget_usd", "monthly_budget_usd", "max_cost_per_ticket",
            "pause_on_exceeded",
            "daily_spend_usd", "monthly_spend_usd",
            "daily_over", "monthly_over",
        )
        row_map = dict(zip(keys, row))
        get = row_map.get
    return BudgetUsage(
        tenant_id=str(get("tenant_id")),
        daily_budget_usd=_to_float(get("daily_budget_usd")),
        monthly_budget_usd=_to_float(get("monthly_budget_usd")),
        max_cost_per_ticket=_to_float(get("max_cost_per_ticket")),
        pause_on_exceeded=bool(get("pause_on_exceeded")),
        daily_spend_usd=float(_to_float(get("daily_spend_usd")) or 0.0),
        monthly_spend_usd=float(_to_float(get("monthly_spend_usd")) or 0.0),
        daily_over=bool(get("daily_over")),
        monthly_over=bool(get("monthly_over")),
    )
