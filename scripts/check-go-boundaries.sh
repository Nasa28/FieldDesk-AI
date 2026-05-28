#!/usr/bin/env bash
#
# Architecture boundary check for the Go API.
#
# Rules:
#   1. apps/api/internal/http/**       must not import a DB driver or sqlc.
#   2. apps/api/internal/handlers/**   must not import a DB driver or sqlc.
#   3. Only apps/api/internal/database/** may call .Query / .QueryRow / .Exec /
#      .Begin / .BeginTx / .CopyFrom on a pgx pool or transaction. Handlers and
#      HTTP must go through the database package.
#
# Test files are exempt — table-driven tests sometimes touch DB primitives
# directly.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d apps/api ]]; then
  echo "apps/api not present; skipping Go boundary checks"
  exit 0
fi

fail=0

report() {
  echo "❌ $1"
  fail=1
}

# Rule 1 + 2: http and handlers must not import DB drivers or sqlc.
while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  case "$file" in
    *_test.go) continue ;;
  esac
  if grep -Eq 'github\.com/jackc/pgx|database/sql|apps/api/internal/database/db' "$file"; then
    report "$file imports a DB driver / sqlc from the HTTP or handler layer; route handlers must call the database package"
  fi
done < <(find apps/api/internal/http apps/api/internal/handlers -type f -name '*.go' 2>/dev/null)

# Rule 3: only the database package may call query/exec/begin APIs.
while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  case "$file" in
    *_test.go) continue ;;
    apps/api/internal/database/*) continue ;;
  esac
  if grep -Eq '\.(Query|QueryRow|Exec|Begin|BeginTx|CopyFrom)\(\s*ctx' "$file"; then
    report "$file calls a database query/exec/begin API outside apps/api/internal/database/"
  fi
done < <(find apps/api -type f -name '*.go' \
  ! -path 'apps/api/tmp/*' \
  ! -path 'apps/api/bin/*' \
  ! -path 'apps/api/dist/*')

if [ "$fail" -eq 0 ]; then
  echo "✓ go boundaries: handlers/http do not import DB drivers; only database package runs queries"
fi
exit "$fail"
