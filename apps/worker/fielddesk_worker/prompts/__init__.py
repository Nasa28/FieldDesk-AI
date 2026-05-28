"""Versioned prompt registry for Phase 5 prompt-version comparison.

Why a registry: the eval CLI's `--compare` flag needs to run the same
golden cases under two different prompts and report the delta. Without a
registry, that means copy-pasting prompt strings into the CLI, which is
how prompts drift in practice.

The registry is intentionally in-process: name → string. We don't store
prompts in the database — operators iterate on prompts in code, ship a
new version, run the comparison, decide whether to promote. The database
path would let prompts change without a deploy, which is a feature for
some teams and a footgun for others. Keep this option open by going via
the registry; punt the database move until a real need surfaces.

When adding a prompt:
  1. Add a `Vx.something` constant body in extraction.py (or a new
     prompts/<kind>.py file).
  2. Register it in EXTRACTION_PROMPTS with a stable version string. Stable
     means "you will not edit the body once it ships" — that's what makes
     ai_eval_runs.prompt_version comparable over time.
  3. To retire a version, leave it in the registry; comparisons against
     archived versions are how you spot a regression that crept back in.
"""

from __future__ import annotations

from fielddesk_worker.prompts.extraction import (
    DEFAULT_EXTRACTION_PROMPT_VERSION,
    EXTRACTION_PROMPTS,
    extraction_prompt_hash,
    get_extraction_prompt,
    list_extraction_prompt_versions,
)

__all__ = [
    "DEFAULT_EXTRACTION_PROMPT_VERSION",
    "EXTRACTION_PROMPTS",
    "extraction_prompt_hash",
    "get_extraction_prompt",
    "list_extraction_prompt_versions",
]
