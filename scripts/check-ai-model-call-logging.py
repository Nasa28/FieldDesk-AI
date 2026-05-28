#!/usr/bin/env python3
"""Enforce AGENTS.md: every AI provider call must be logged to ai_model_calls.

For each worker service module that calls a provider (`provider.transcribe(`,
`provider.extract_ticket(`, `provider.embed(`, `provider.complete_json(`),
require that the same file also references `insert_model_call(` or
`log_model_call_isolated(`.

Escape hatch: add `# lint-ai-logging: <reason>` anywhere in the file.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKER_DIR = ROOT / "apps" / "worker" / "fielddesk_worker"

PROVIDER_CALL_RE = re.compile(
    r"\bprovider\.(transcribe|extract_ticket|embed|complete_json)\s*\("
)
LOGGER_RE = re.compile(r"\b(insert_model_call|log_model_call_isolated)\s*\(")
ESCAPE_RE = re.compile(r"#\s*lint-ai-logging:")


def main() -> int:
    if not WORKER_DIR.exists():
        print(f"{WORKER_DIR} not present; skipping AI logging check")
        return 0

    fail = False
    checked = 0

    for path in sorted(WORKER_DIR.rglob("*.py")):
        if any(part in {"__pycache__", "tests", ".venv"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")

        if not PROVIDER_CALL_RE.search(text):
            continue

        checked += 1
        if ESCAPE_RE.search(text):
            continue
        if not LOGGER_RE.search(text):
            rel = path.relative_to(ROOT)
            print(
                f"❌ {rel}: calls a provider method but does not log to ai_model_calls "
                "(insert_model_call / log_model_call_isolated)."
            )
            fail = True

    if fail:
        print(
            "\nAGENTS.md: 'Every AI call must be logged.' Wire an "
            "insert_model_call() (or log_model_call_isolated() for failures) into "
            "this handler, or add `# lint-ai-logging: <reason>` if this is genuinely "
            "not a provider-billing path."
        )
        return 1

    print(f"✓ ai model-call logging: {checked} provider-calling file(s) all log to ai_model_calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
