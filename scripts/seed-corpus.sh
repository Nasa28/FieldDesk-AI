#!/usr/bin/env bash
# Upload the Phase 4c golden corpus (5 markdown SOPs / manuals) into a
# tenant via the documents API, so the rag eval has something real to
# retrieve against. Idempotent only insofar as repeated runs create new
# document rows — delete first if you want clean numbers.
#
# Usage:
#   ./scripts/seed-corpus.sh <tenant-uuid> [api-url] [--wait]
#
# Example:
#   TENANT=$(./scripts/seed.sh)
#   ./scripts/seed-corpus.sh "$TENANT" http://localhost:8080 --wait
#   ./scripts/eval.sh "$TENANT" all

set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "usage: $0 <tenant-uuid> [api-url] [--wait]" >&2
    exit 64
fi

TENANT="$1"
API_URL="${2:-http://localhost:8080}"
WAIT_FLAG=""
WAIT_SECONDS=120

# A bare --wait flag means "wait until every doc is ready or timeout".
# Reusing seed_corpus.py's --wait-seconds avoids reimplementing polling.
for arg in "$@"; do
    if [ "$arg" = "--wait" ]; then
        WAIT_FLAG="--wait-seconds $WAIT_SECONDS"
    fi
done

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
fi

cd "$ROOT"
exec "$PYTHON_BIN" -m fielddesk_worker.evals.seed_corpus \
    --tenant "$TENANT" \
    --api-url "$API_URL" \
    $WAIT_FLAG
