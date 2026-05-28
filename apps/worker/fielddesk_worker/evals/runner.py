"""Eval runner.

Loads `ai_eval_cases`, runs the current extraction or RAG pipeline against
each one, and writes results to `ai_eval_runs`. Metrics include JSON
validity rate, required field completion, exact-match per field, and
retrieval hit rate.
"""

from __future__ import annotations

from typing import Any


def run_extraction_evals(prompt_version: str) -> dict[str, Any]:
    """Run extraction evals against the golden set."""
    # TODO: load ai_eval_cases where kind='extraction'.
    return {"prompt_version": prompt_version, "cases": 0, "stub": True}


def run_rag_evals(prompt_version: str) -> dict[str, Any]:
    """Run RAG evals against the golden set."""
    # TODO: load ai_eval_cases where kind='rag'.
    return {"prompt_version": prompt_version, "cases": 0, "stub": True}
