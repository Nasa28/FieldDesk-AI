"""Phase 5 — prompt-version comparison.

Runs the extraction injection eval suite under two (or more) prompt
versions in the same operator command and reports the side-by-side delta.
Each version's run still produces its own ai_eval_runs row, so a charting
dashboard sees the time-series for every version independently AND the
comparison report gives the operator the at-a-glance number.

This is what closes Phase 5 of the PRD §19 roadmap. Comparison is
extraction-only in v1 because that's where the prompt is the main lever;
RAG retrieval doesn't have an analogous "prompt version" knob. When/if we
add prompt-driven RAG synthesis or rerank judgments, this module gets a
new `kind` parameter; today the API is shaped to make that future
expansion obvious.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog

from fielddesk_worker.evals.runner import run_extraction_evals
from fielddesk_worker.prompts import (
    extraction_prompt_hash,
    list_extraction_prompt_versions,
)

log = structlog.get_logger()


@dataclass
class VersionResult:
    """One row of the comparison table."""

    prompt_version: str
    prompt_hash: str
    injection_resistance_rate: float
    total_cases: int
    duration_seconds: float


@dataclass
class ComparisonReport:
    tenant_id: str
    baseline_version: str
    versions: list[VersionResult]

    @property
    def baseline(self) -> VersionResult:
        for v in self.versions:
            if v.prompt_version == self.baseline_version:
                return v
        # Defensive: the CLI guarantees baseline is in the list, but if a
        # caller bypasses that we want a clear error, not an IndexError.
        raise KeyError(f"baseline {self.baseline_version!r} missing from results")

    def deltas(self) -> list[tuple[VersionResult, float]]:
        """Return (version, delta_vs_baseline) pairs, baseline first."""
        base_rate = self.baseline.injection_resistance_rate
        out: list[tuple[VersionResult, float]] = []
        for v in self.versions:
            delta = v.injection_resistance_rate - base_rate
            out.append((v, delta))
        return out

    def regressed(self, threshold: float = 0.0) -> bool:
        """True if any non-baseline version scored worse than the baseline
        by more than `threshold`. CI uses this to fail the build."""
        base = self.baseline.injection_resistance_rate
        for v in self.versions:
            if v.prompt_version == self.baseline_version:
                continue
            if v.injection_resistance_rate < (base - threshold):
                return True
        return False


def run_extraction_comparison(
    tenant_id: str | UUID,
    versions: list[str],
    *,
    baseline_version: str | None = None,
) -> ComparisonReport:
    """Run the extraction injection eval against each version in `versions`
    and return a side-by-side report. `baseline_version` defaults to the
    first entry — typically the production prompt — so the delta column
    reads as "candidate − baseline."

    Each version's run writes its own ai_eval_runs row with the correct
    prompt_version; this function does not write a separate comparison
    record. The comparison IS the operator's view; the rows are the
    durable record.
    """
    if not versions:
        raise ValueError("at least one version is required")
    known = set(list_extraction_prompt_versions())
    unknown = [v for v in versions if v not in known]
    if unknown:
        raise KeyError(
            f"unknown extraction prompt version(s): {unknown}; "
            f"known: {sorted(known)}"
        )
    tenant_id = str(tenant_id)
    baseline = baseline_version or versions[0]
    if baseline not in versions:
        raise ValueError(
            f"baseline {baseline!r} must appear in --compare list {versions!r}"
        )

    results: list[VersionResult] = []
    for version in versions:
        started = time.perf_counter()
        metrics = run_extraction_evals(tenant_id, prompt_version=version)
        elapsed = time.perf_counter() - started
        results.append(
            VersionResult(
                prompt_version=version,
                prompt_hash=extraction_prompt_hash(version),
                injection_resistance_rate=float(
                    metrics.get("injection_resistance_rate", 0.0)
                ),
                total_cases=len(metrics.get("cases", [])),
                duration_seconds=elapsed,
            )
        )

    report = ComparisonReport(
        tenant_id=tenant_id,
        baseline_version=baseline,
        versions=results,
    )
    log.info(
        "extraction_prompt_comparison_completed",
        tenant_id=tenant_id,
        baseline=baseline,
        versions=[v.prompt_version for v in results],
        regressed=report.regressed(),
    )
    return report


def render_report(report: ComparisonReport, *, threshold: float = 0.0) -> str:
    """Format the comparison as a fixed-width plaintext table. Reads cleanly
    in a terminal, in a cron-mail body, and in the GitHub Actions summary
    panel — three places this will land most often. `threshold` must match
    the CLI's regression threshold so stderr, JSON, and exit code agree."""
    lines: list[str] = []
    lines.append(
        f"Extraction prompt comparison — tenant {report.tenant_id}, "
        f"baseline {report.baseline_version}"
    )
    lines.append("")
    header = (
        f"{'version':38} {'hash':<16} {'inj_resist':>10} "
        f"{'delta':>8} {'cases':>6} {'sec':>6}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for version, delta in report.deltas():
        delta_str = (
            f"{delta:+.3f}"
            if version.prompt_version != report.baseline_version
            else "  base"
        )
        lines.append(
            f"{version.prompt_version:38} {version.prompt_hash:<16} "
            f"{version.injection_resistance_rate:>10.3f} {delta_str:>8} "
            f"{version.total_cases:>6} {version.duration_seconds:>6.1f}"
        )
    lines.append("")
    if report.regressed(threshold=threshold):
        lines.append(
            "REGRESSION: at least one non-baseline version scored worse than baseline."
        )
    else:
        if threshold > 0:
            lines.append(f"No regression vs baseline within threshold {threshold:.3f}.")
        else:
            lines.append("No regression vs baseline.")
    return "\n".join(lines)
