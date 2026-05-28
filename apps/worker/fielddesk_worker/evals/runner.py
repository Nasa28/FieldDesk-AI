from __future__ import annotations

from typing import Any


# TODO: load ai_eval_cases where kind='extraction', run pipeline, write ai_eval_runs.
def run_extraction_evals(prompt_version: str) -> dict[str, Any]:
    return {"stub": True, "prompt_version": prompt_version, "cases": 0}


# TODO: load ai_eval_cases where kind='rag', run pipeline, write ai_eval_runs.
def run_rag_evals(prompt_version: str) -> dict[str, Any]:
    return {"stub": True, "prompt_version": prompt_version, "cases": 0}
