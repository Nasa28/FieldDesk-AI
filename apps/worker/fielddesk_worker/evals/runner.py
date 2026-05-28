"""Phase 4c eval orchestrator.

Two pipelines, both tenant-scoped, each writing one row to ai_eval_runs:

  run_rag_evals: for each golden RAG case, embed the query, run the same
    hybrid_search the worker uses on real tickets, and check whether any of
    the expected document titles appears in the top-K results. Reports
    recall@K and MRR (first-hit reciprocal rank).

  run_extraction_evals: for each injection case, run the extraction provider
    against the hostile transcript and verify the hardened prompt held.
    Implementation lives in evals/extraction.py.

Both runners are operator-driven CLI runs (not job-queue handlers) that
produce a comparable record over time.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

import structlog
from psycopg.rows import dict_row

from fielddesk_worker.db import conn
from fielddesk_worker.db_queries import log_model_call_isolated
from fielddesk_worker.embeddings.service import _make_provider as _make_embedding_provider
from fielddesk_worker.evals import extraction as extraction_eval
from fielddesk_worker.evals import recommendations as recs_eval
from fielddesk_worker.evals._provider_info import provider_model, provider_name
from fielddesk_worker.evals.golden import (
    GOLDEN_EXTRACTION_INJECTION_CASES,
    GOLDEN_RAG_CASES,
    GOLDEN_RECS_INJECTION_CASES,
    RAGCase,
)
from fielddesk_worker.evals.persistence import write_eval_run, write_failed_eval_run
from fielddesk_worker.prompts import (
    DEFAULT_EXTRACTION_PROMPT_VERSION,
    extraction_prompt_hash,
)
from fielddesk_worker.rag.retrieval import retrieve_with_optional_rerank

log = structlog.get_logger()

RAG_PROMPT_VERSION = "rag.hybrid.v1"
EXTRACTION_PROMPT_VERSION = DEFAULT_EXTRACTION_PROMPT_VERSION
RECS_PROMPT_VERSION = "recs.v1.injection-hardened"


@dataclass
class RAGCaseResult:
    name: str
    query_text: str
    expected_titles: list[str]
    found_titles: list[str]
    hit_rank: int | None  # 1-indexed rank of the first expected title, or None
    passed: bool


def run_rag_evals(
    tenant_id: str | UUID,
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """Run the golden RAG cases against the tenant's current corpus.

    Failure modes worth naming:
      - Tenant has no documents → every case fails. The CLI warns rather
        than treating it as a regression — operator forgot to seed.
      - Embedding provider is the stub → vectors are deterministic but
        semantically meaningless; recall will be near-random.
    """
    started_at = time.time()
    tenant_id = str(tenant_id)
    provider = None
    results: list[RAGCaseResult] = []
    chunk_count = 0
    try:
        provider = _make_embedding_provider()
        with conn() as c:
            c.row_factory = dict_row
            with c.transaction():
                with c.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) AS n FROM document_chunks WHERE tenant_id = %s",
                        (tenant_id,),
                    )
                    row = cur.fetchone()
                    chunk_count = int((row or {}).get("n", 0))
                    for case in GOLDEN_RAG_CASES:
                        results.append(
                            _run_one_rag_case(cur, tenant_id, case, provider, top_k)
                        )
    except Exception as exc:  # noqa: BLE001
        write_failed_eval_run(
            tenant_id=tenant_id,
            kind="rag",
            prompt_version=RAG_PROMPT_VERSION,
            model=provider_model(provider) if provider is not None else "?",
            total_cases=len(GOLDEN_RAG_CASES),
            metrics={
                "top_k": top_k,
                "recall_at_k": 0.0,
                "mrr": 0.0,
                "tenant_chunk_count": chunk_count,
                "completed_cases": len(results),
                "cases": [asdict(r) for r in results],
            },
            started_at=started_at,
            exc=exc,
        )
        raise

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    mrr = (
        sum(1.0 / r.hit_rank for r in results if r.hit_rank is not None) / total
        if total
        else 0.0
    )
    recall_at_k = passed / total if total else 0.0
    # recall@1 and recall@3 are the metrics that actually move when
    # reranking lands. recall@5 is structurally saturated whenever the
    # corpus is <= top_k (every case can find its doc somewhere), but
    # the rank-bucketed numbers reveal precision at the top. We compute
    # all three so future eval runs can chart top-1 / top-3 alongside
    # top-K without re-defining the case set.
    recall_at_1 = (
        sum(1 for r in results if r.hit_rank is not None and r.hit_rank <= 1)
        / total
        if total
        else 0.0
    )
    recall_at_3 = (
        sum(1 for r in results if r.hit_rank is not None and r.hit_rank <= 3)
        / total
        if total
        else 0.0
    )

    metrics: dict[str, Any] = {
        "top_k": top_k,
        "recall_at_1": recall_at_1,
        "recall_at_3": recall_at_3,
        "recall_at_k": recall_at_k,
        "mrr": mrr,
        "tenant_chunk_count": chunk_count,
        "cases": [asdict(r) for r in results],
    }
    write_eval_run(
        tenant_id=tenant_id,
        kind="rag",
        prompt_version=RAG_PROMPT_VERSION,
        model=provider_model(provider),
        total_cases=total,
        passed=passed,
        failed=total - passed,
        metrics=metrics,
        started_at=started_at,
    )
    log.info(
        "rag_eval_completed",
        tenant_id=tenant_id,
        total=total,
        passed=passed,
        recall_at_k=recall_at_k,
        mrr=mrr,
        chunks=chunk_count,
    )
    return metrics

def _run_one_rag_case(
    cur, tenant_id: str, case: RAGCase, provider, top_k: int
) -> RAGCaseResult:
    started = time.perf_counter()
    try:
        vectors, metrics = provider.embed([case.query_text])
    except Exception as exc:  # noqa: BLE001
        log_model_call_isolated(
            tenant_id=tenant_id,
            job_id=None,
            kind="embedding",
            provider=provider_name(provider),
            model=provider_model(provider),
            duration_ms=int((time.perf_counter() - started) * 1000),
            success=False,
            cost_usd=0.0,
            error_class=type(exc).__name__,
            error_message=str(exc)[:1000],
            request_meta={"eval": True, "case_name": case.name},
        )
        raise
    # AGENTS.md: every provider call gets a row in ai_model_calls. Isolated
    # logger so the eval transaction can roll back without losing the cost
    # record — eval runs are real spend the operator should see.
    log_model_call_isolated(
        tenant_id=tenant_id,
        job_id=None,
        kind="embedding",
        provider=metrics.provider,
        model=metrics.model,
        duration_ms=metrics.duration_ms,
        success=metrics.success,
        input_tokens=metrics.input_tokens,
        cost_usd=metrics.cost_usd,
        request_meta={"eval": True, "case_name": case.name},
    )
    if not vectors:
        return RAGCaseResult(
            name=case.name,
            query_text=case.query_text,
            expected_titles=list(case.expected_document_titles),
            found_titles=[],
            hit_rank=None,
            passed=False,
        )
    literal = "[" + ",".join(f"{x:.7f}" for x in vectors[0]) + "]"
    # Eval runs the same two-stage path production uses, so a recall@1
    # improvement here matches what real RAG queries will see — otherwise
    # the eval is measuring a different system than the one we ship.
    rows, rerank_metrics = retrieve_with_optional_rerank(
        cur,
        tenant_id=tenant_id,
        query_text=case.query_text,
        embedding_literal=literal,
        top_k=top_k,
    )
    if rerank_metrics is not None:
        # Tag the rerank call as eval-side so the cost dashboard can
        # split eval rerank spend from production rerank spend, same
        # posture as the existing embedding-eval cost rows.
        log_model_call_isolated(
            tenant_id=tenant_id,
            job_id=None,
            kind="rerank",
            provider=rerank_metrics.provider,
            model=rerank_metrics.model,
            duration_ms=rerank_metrics.duration_ms,
            success=rerank_metrics.success,
            cost_usd=rerank_metrics.cost_usd,
            error_class=rerank_metrics.error_class,
            error_message=rerank_metrics.error_message,
            request_meta={
                "eval": True,
                "case_name": case.name,
                "candidate_count": rerank_metrics.candidate_count,
                **rerank_metrics.extra,
            },
        )
    found_titles: list[str] = []
    hit_rank: int | None = None
    expected_set = set(case.expected_document_titles)
    for idx, row in enumerate(rows, start=1):
        title = str(row.get("document_title", ""))
        found_titles.append(title)
        if hit_rank is None and title in expected_set:
            hit_rank = idx
    return RAGCaseResult(
        name=case.name,
        query_text=case.query_text,
        expected_titles=list(case.expected_document_titles),
        found_titles=found_titles,
        hit_rank=hit_rank,
        passed=hit_rank is not None,
    )


def run_extraction_evals(
    tenant_id: str | UUID,
    *,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    """Run the canonical prompt-injection cases through the live extraction
    provider. Implementation in evals/extraction.py; this function only
    handles persistence so all ai_eval_runs writes go through one place.

    `prompt_version` overrides which prompt body the provider sees — Phase 5
    `--compare` calls this once per version. Default behavior (None) matches
    the production path."""
    started_at = time.time()
    tenant_id = str(tenant_id)
    try:
        metrics, passed, total, model_name, resolved_version = extraction_eval.run(
            tenant_id, prompt_version=prompt_version
        )
    except Exception as exc:  # noqa: BLE001
        failed_prompt_version = prompt_version or EXTRACTION_PROMPT_VERSION
        failed_metrics: dict[str, Any] = {
            "injection_resistance_rate": 0.0,
            "completed_cases": 0,
            "cases": [],
            "prompt_version": failed_prompt_version,
        }
        try:
            failed_metrics["prompt_hash"] = extraction_prompt_hash(failed_prompt_version)
        except KeyError:
            pass
        write_failed_eval_run(
            tenant_id=tenant_id,
            kind="extraction",
            prompt_version=failed_prompt_version,
            model="?",
            total_cases=len(GOLDEN_EXTRACTION_INJECTION_CASES),
            metrics=failed_metrics,
            started_at=started_at,
            exc=exc,
        )
        raise
    write_eval_run(
        tenant_id=tenant_id,
        kind="extraction",
        prompt_version=resolved_version,
        model=model_name,
        total_cases=total,
        passed=passed,
        failed=total - passed,
        metrics=metrics,
        started_at=started_at,
    )
    return metrics


def run_recs_evals(tenant_id: str | UUID) -> dict[str, Any]:
    """Run the hostile-chunk synthesis cases through the live LLM provider.

    Same structural contract as run_extraction_evals: persistence stays here
    so all ai_eval_runs writes go through one place; the pipeline body lives
    in evals/recommendations.py. Kind is 'recs' (added to the CHECK in
    migration 00019).
    """
    started_at = time.time()
    tenant_id = str(tenant_id)
    try:
        metrics, passed, total, model_name = recs_eval.run(tenant_id)
    except Exception as exc:  # noqa: BLE001
        write_failed_eval_run(
            tenant_id=tenant_id,
            kind="recs",
            prompt_version=RECS_PROMPT_VERSION,
            model="?",
            total_cases=len(GOLDEN_RECS_INJECTION_CASES),
            metrics={
                "injection_resistance_rate": 0.0,
                "completed_cases": 0,
                "cases": [],
            },
            started_at=started_at,
            exc=exc,
        )
        raise
    write_eval_run(
        tenant_id=tenant_id,
        kind="recs",
        prompt_version=RECS_PROMPT_VERSION,
        model=model_name,
        total_cases=total,
        passed=passed,
        failed=total - passed,
        metrics=metrics,
        started_at=started_at,
    )
    return metrics
