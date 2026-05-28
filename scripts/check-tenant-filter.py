#!/usr/bin/env python3
"""Enforce AGENTS.md: every database query must filter by tenant_id.

For each `*.go` file under apps/api/internal/database/, extract every
backtick-delimited SQL string literal. For each `*.py` file under
apps/worker/fielddesk_worker/db_queries/, extract Python string constants.
If a literal contains a `WHERE` clause and does NOT mention `tenant_id`
anywhere in the literal, flag it.

Also extracts query strings from apps/api/sql/queries/*.sql.

Escape hatch: add `// lint-tenant-filter: <reason>` on the line immediately
before the opening backtick (Go) or on the line immediately above the
`-- name:` annotation (sqlc query file). In Python, add
`# lint-tenant-filter: <reason>` immediately above the string.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "apps" / "api" / "internal" / "database"
SQL_DIR = ROOT / "apps" / "api" / "sql" / "queries"
WORKER_QUERY_DIR = ROOT / "apps" / "worker" / "fielddesk_worker" / "db_queries"

# Multi-line Go string literal — backticks.
GO_STRING_RE = re.compile(r"`([^`]+)`", re.DOTALL)
WHERE_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)
TENANT_RE = re.compile(r"\btenant_id\b", re.IGNORECASE)
ESCAPE_RE = re.compile(r"lint-tenant-filter:")
# `-- name: Foo :one` etc. — sqlc query annotation.
SQLC_NAME_RE = re.compile(r"^--\s*name:\s*(\S+)", re.IGNORECASE)


def has_escape_hatch_before(content: str, offset: int) -> bool:
    lines_before = content[:offset].splitlines()
    if not lines_before:
        return False
    return bool(ESCAPE_RE.search(lines_before[-1]))


def has_escape_hatch_before_line(content: str, lineno: int) -> bool:
    lines = content.splitlines()
    if lineno <= 1 or lineno - 2 >= len(lines):
        return False
    return bool(ESCAPE_RE.search(lines[lineno - 2]))


def check_go_files() -> list[tuple[pathlib.Path, int, str]]:
    findings: list[tuple[pathlib.Path, int, str]] = []
    if not DB_DIR.exists():
        return findings
    for path in sorted(DB_DIR.glob("*.go")):
        if path.name.endswith("_test.go"):
            continue
        content = path.read_text(encoding="utf-8")
        for match in GO_STRING_RE.finditer(content):
            body = match.group(1)
            if not WHERE_RE.search(body):
                continue
            if TENANT_RE.search(body):
                continue
            if has_escape_hatch_before(content, match.start()):
                continue
            line = content.count("\n", 0, match.start()) + 1
            snippet = body.strip().splitlines()[0][:120]
            findings.append((path, line, snippet))
    return findings


def check_python_query_files() -> list[tuple[pathlib.Path, int, str]]:
    findings: list[tuple[pathlib.Path, int, str]] = []
    if not WORKER_QUERY_DIR.exists():
        return findings
    for path in sorted(WORKER_QUERY_DIR.glob("*.py")):
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            body = node.value
            if not WHERE_RE.search(body):
                continue
            if TENANT_RE.search(body):
                continue
            if has_escape_hatch_before_line(content, node.lineno):
                continue
            snippet = body.strip().splitlines()[0][:120]
            findings.append((path, node.lineno, snippet))
    return findings


def split_sqlc_queries(content: str) -> list[tuple[int, str]]:
    """Split a sqlc query file into (start_line, query_text) chunks per `-- name:`."""
    chunks: list[tuple[int, str]] = []
    current: list[str] = []
    current_line = 0
    for lineno, line in enumerate(content.splitlines(), start=1):
        if SQLC_NAME_RE.match(line):
            if current:
                chunks.append((current_line, "\n".join(current)))
            current = [line]
            current_line = lineno
        else:
            current.append(line)
    if current:
        chunks.append((current_line, "\n".join(current)))
    return chunks


def check_sqlc_queries() -> list[tuple[pathlib.Path, int, str]]:
    findings: list[tuple[pathlib.Path, int, str]] = []
    if not SQL_DIR.exists():
        return findings
    for path in sorted(SQL_DIR.glob("*.sql")):
        content = path.read_text(encoding="utf-8")
        for start_line, chunk in split_sqlc_queries(content):
            if ESCAPE_RE.search(chunk):
                continue
            if not WHERE_RE.search(chunk):
                continue
            if TENANT_RE.search(chunk):
                continue
            first_sql_line = next(
                (ln for ln in chunk.splitlines() if not ln.lstrip().startswith("--")),
                chunk.splitlines()[0] if chunk.splitlines() else "",
            )
            findings.append((path, start_line, first_sql_line.strip()[:120]))
    return findings


def main() -> int:
    findings = check_go_files() + check_python_query_files() + check_sqlc_queries()
    if findings:
        print("❌ tenant filter: SQL queries with WHERE but no tenant_id reference:")
        for path, line, snippet in findings:
            rel = path.relative_to(ROOT)
            print(f"   {rel}:{line}: {snippet}")
        print(
            "\nAGENTS.md: 'Tenant boundaries are sacred. Every query filters by "
            "tenant_id at the outermost level.' Add `tenant_id` to the WHERE/ON "
            "clauses, or add `// lint-tenant-filter: <reason>` on the line above "
            "the query if this is a legitimately tenant-agnostic path "
            "(e.g. health checks)."
        )
        return 1
    print("✓ tenant filter: every WHERE clause in database queries includes tenant_id")
    return 0


if __name__ == "__main__":
    sys.exit(main())
