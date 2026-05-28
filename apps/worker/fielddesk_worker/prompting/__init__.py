"""Shared prompt-construction helpers.

Why a separate module: AGENTS.md "Prompt injection" mandates that every LLM
call that ingests user-controllable text wrap that text in escaped delimiters
and explicitly mark it as untrusted in the system prompt. Putting the wrapper
in one place means future call sites (RAG synthesis, draft_ticket, future
agents) inherit the canonical implementation rather than each rolling their
own — which is exactly how injection regressions creep in.
"""

from __future__ import annotations

from fielddesk_worker.prompting.safety import (
    wrap_untrusted_chunk,
    wrap_untrusted_chunks,
    wrap_untrusted_ticket_summary,
    wrap_untrusted_transcript,
)

__all__ = [
    "wrap_untrusted_chunk",
    "wrap_untrusted_chunks",
    "wrap_untrusted_ticket_summary",
    "wrap_untrusted_transcript",
]
