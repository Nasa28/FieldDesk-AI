from __future__ import annotations

from typing import Any

from fielddesk_worker.embeddings.chunker import Chunk


CONTEXTUAL_RETRIEVAL_VERSION = "deterministic-metadata-v1"
MAX_CONTEXT_CHARS = 600


def build_retrieval_text(*, document_title: str, chunk: Chunk) -> str:
    """Build the text sent to embedding and lexical search.

    The raw chunk stays untouched for citations/UI. This retrieval-only
    string gives small chunks enough document/section context to survive a
    larger corpus without adding another LLM call at ingest time.
    """
    context = _context_lines(document_title=document_title, chunk=chunk)
    if not context:
        return chunk.text
    return f"{context}\n\n{chunk.text}"


def _context_lines(*, document_title: str, chunk: Chunk) -> str:
    parts: list[str] = []
    title = _clean(document_title)
    if title:
        parts.append(f"Document: {title}")

    heading_path = [_clean(h) for h in chunk.heading_path]
    heading_path = [h for h in heading_path if h]
    if heading_path:
        parts.append("Section: " + " > ".join(heading_path))

    if chunk.source_page is not None:
        parts.append(f"Page: {chunk.source_page}")

    slide = _locator_value(chunk.source_locator, "slide")
    if slide is not None:
        parts.append(f"Slide: {_clean(slide)}")

    context = "\n".join(parts).strip()
    if len(context) <= MAX_CONTEXT_CHARS:
        return context
    return context[:MAX_CONTEXT_CHARS].rstrip()


def _locator_value(source_locator: dict[str, Any] | None, key: str) -> Any | None:
    if not source_locator:
        return None
    value = source_locator.get(key)
    if value is None or value == "":
        return None
    return value


def _clean(value: Any) -> str:
    return " ".join(str(value).split())
