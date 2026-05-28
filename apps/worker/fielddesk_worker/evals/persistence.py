from __future__ import annotations

from typing import Any

import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fielddesk_worker.db import conn

log = structlog.get_logger()


def write_eval_run(
    *,
    tenant_id: str,
    kind: str,
    prompt_version: str,
    model: str,
    total_cases: int,
    passed: int,
    failed: int,
    metrics: dict[str, Any],
    started_at: float,
) -> None:
    with conn() as c:
        c.row_factory = dict_row
        with c.transaction():
            with c.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_eval_runs
                        (tenant_id, kind, prompt_version, model,
                         total_cases, passed, failed, metrics,
                         started_at, finished_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                            to_timestamp(%s), now())
                    """,
                    (
                        tenant_id, kind, prompt_version, model,
                        total_cases, passed, failed, Jsonb(metrics),
                        started_at,
                    ),
                )


def write_failed_eval_run(
    *,
    tenant_id: str,
    kind: str,
    prompt_version: str,
    model: str,
    total_cases: int,
    metrics: dict[str, Any],
    started_at: float,
    exc: Exception,
) -> None:
    failure_metrics = {
        **metrics,
        "failed_before_completion": True,
        "error": {
            "class": type(exc).__name__,
            "message": str(exc)[:1000],
        },
    }
    try:
        write_eval_run(
            tenant_id=tenant_id,
            kind=kind,
            prompt_version=prompt_version,
            model=model,
            total_cases=total_cases,
            passed=0,
            failed=total_cases,
            metrics=failure_metrics,
            started_at=started_at,
        )
    except Exception as write_exc:  # noqa: BLE001
        log.error(
            "eval_failure_record_failed",
            tenant_id=tenant_id,
            kind=kind,
            error_class=type(write_exc).__name__,
            error_message=str(write_exc),
            original_error_class=type(exc).__name__,
            original_error_message=str(exc),
        )
