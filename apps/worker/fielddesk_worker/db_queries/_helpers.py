from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()


def returned_id(row: Any) -> str:
    if isinstance(row, dict):
        return row["id"]
    return row[0]
