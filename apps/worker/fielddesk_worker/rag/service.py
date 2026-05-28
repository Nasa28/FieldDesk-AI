from __future__ import annotations

from typing import Any


# TODO: build query from extraction, embed, vector search (tenant-scoped), persist results.
def retrieve(job: dict[str, Any], cur) -> dict[str, Any]:
    return {"stub": True, "job_id": str(job.get("id"))}
