#!/usr/bin/env bash
# Apply Goose migrations against the local Postgres container.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${ROOT}/infra/migrations"

if ! command -v goose >/dev/null 2>&1; then
  echo "goose not installed. Install with: go install github.com/pressly/goose/v3/cmd/goose@latest" >&2
  exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is required. Source .env or export it before running this script." >&2
  exit 1
fi

goose -dir "${DIR}" postgres "${DATABASE_URL}" "${1:-up}"
