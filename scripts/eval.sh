#!/usr/bin/env bash
# Operator-facing wrapper for the Phase 4c eval CLI.
#
# Usage:
#   ./scripts/eval.sh <tenant-uuid> [rag|extraction|all]
#
# Run on the host with the worker venv active, OR via docker-compose:
#   docker compose run --rm worker ./scripts/eval.sh <tenant-uuid>
#
# Exit code is 0 when every requested suite clears the CLI's stability gates
# (RAG recall@1/recall@K plus 100% injection resistance by default).
# Pair with cron (see infra/cron/evals.crontab) for nightly regression alerts.

set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "usage: $0 <tenant-uuid> [rag|extraction|all]" >&2
    exit 64
fi

TENANT="$1"
KIND="${2:-all}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER_SRC="$ROOT/apps/worker"

if [ -n "${FIELDDESK_WORKER_PYTHON:-}" ]; then
    PYTHON_BIN="$FIELDDESK_WORKER_PYTHON"
elif [ -x "$WORKER_SRC/.venv/bin/python" ]; then
    PYTHON_BIN="$WORKER_SRC/.venv/bin/python"
else
    PYTHON_BIN="${PYTHON:-python3}"
fi

if [ -d "$WORKER_SRC/fielddesk_worker" ]; then
    export PYTHONPATH="$WORKER_SRC${PYTHONPATH:+:$PYTHONPATH}"
elif [ -d "$ROOT/fielddesk_worker" ]; then
    export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
fi

cd "$ROOT"
exec "$PYTHON_BIN" -m fielddesk_worker.evals --tenant "$TENANT" --kind "$KIND"
