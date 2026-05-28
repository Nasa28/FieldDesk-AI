"""CLI entry-point for the Phase 4c evals.

Usage:
    python -m fielddesk_worker.evals --tenant <uuid> --kind rag [--top-k 5]
    python -m fielddesk_worker.evals --tenant <uuid> --kind extraction
    python -m fielddesk_worker.evals --tenant <uuid> --kind recs
    python -m fielddesk_worker.evals --tenant <uuid> --kind all

Why a CLI rather than a worker job: evals are operator-driven and shouldn't
share the `ai_jobs` queue (a stuck eval would block real work, and eval
results aren't tenant-facing on a schedule). Runs are written to
ai_eval_runs so dashboards can chart pass rate over time.
"""

from __future__ import annotations

import argparse
import json
import sys

from fielddesk_worker.evals.runner import (
    run_extraction_evals,
    run_rag_evals,
    run_recs_evals,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fielddesk_worker.evals")
    parser.add_argument(
        "--tenant",
        required=True,
        help="Tenant UUID to run evals against (matches the X-Tenant-ID used elsewhere).",
    )
    parser.add_argument(
        "--kind",
        choices=["rag", "extraction", "recs", "all"],
        default="all",
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)

    out: dict[str, dict] = {}
    if args.kind in ("rag", "all"):
        out["rag"] = run_rag_evals(args.tenant, top_k=args.top_k)
    if args.kind in ("extraction", "all"):
        out["extraction"] = run_extraction_evals(args.tenant)
    if args.kind in ("recs", "all"):
        out["recs"] = run_recs_evals(args.tenant)

    json.dump(out, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")

    # Exit code reflects whether every requested suite achieved a pass rate
    # above a conservative threshold (50%). A CI / nightly run can then fail
    # noisily on regressions instead of just printing them.
    threshold = 0.5
    any_failed = False
    if "rag" in out and out["rag"].get("recall_at_k", 0.0) < threshold:
        any_failed = True
    if "extraction" in out and out["extraction"].get("injection_resistance_rate", 0.0) < threshold:
        any_failed = True
    if "recs" in out and out["recs"].get("injection_resistance_rate", 0.0) < threshold:
        any_failed = True
    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
