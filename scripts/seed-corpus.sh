#!/usr/bin/env bash
# Upload the Phase 4c golden corpus (5 markdown SOPs / manuals) into a
# tenant via the documents API, so the rag eval has something real to
# retrieve against. Idempotent only insofar as repeated runs create new
# document rows — delete first if you want clean numbers.
#
# Usage:
#   ./scripts/seed-corpus.sh <tenant-uuid> [api-url] [--wait | --wait-seconds N]
#
# Example:
#   TENANT=$(./scripts/seed.sh)
#   ./scripts/seed-corpus.sh "$TENANT" http://localhost:8080 --wait
#   ./scripts/eval.sh "$TENANT" all

set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "usage: $0 <tenant-uuid> [api-url] [--wait | --wait-seconds N]" >&2
    exit 64
fi

TENANT="$1"
shift

API_URL="http://localhost:8080"
API_URL_SET=0
WAIT_SECONDS=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --wait)
            WAIT_SECONDS=120
            shift
            ;;
        --wait-seconds)
            if [ "$#" -lt 2 ]; then
                echo "--wait-seconds requires a value" >&2
                exit 64
            fi
            WAIT_SECONDS="$2"
            shift 2
            ;;
        --*)
            echo "unknown option: $1" >&2
            exit 64
            ;;
        *)
            if [ "$API_URL_SET" -eq 1 ]; then
                echo "unexpected argument: $1" >&2
                exit 64
            fi
            API_URL="$1"
            API_URL_SET=1
            shift
            ;;
    esac
done

WAIT_ARGS=()
if [ "$WAIT_SECONDS" != "0" ]; then
    WAIT_ARGS=(--wait-seconds "$WAIT_SECONDS")
fi

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
    "${WAIT_ARGS[@]}"
