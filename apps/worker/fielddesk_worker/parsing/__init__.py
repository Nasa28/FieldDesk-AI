"""Document parsing layer for Phase 4 RAG ingest.

Each parser converts bytes to a sequence of `ParsedSegment` records that carry
just enough context for the chunker to produce a faithful citation later:
heading path, page number (PDF), and a generic JSON locator for anything we
need to add without ALTERing the chunks table again.

Supported in v1: .txt, .md, text-native .pdf, .docx.
Deferred: scanned PDFs / OCR, encrypted PDFs, .doc, .pptx, table extraction
as structured data. A failed parse should land the document in `status =
'failed'` with `parse_error` set, never produce partial chunks.
"""

from __future__ import annotations

from fielddesk_worker.parsing.base import (
    ParseError,
    ParsedSegment,
    SUPPORTED_MIME_TYPES,
    parse_document,
)

__all__ = [
    "ParseError",
    "ParsedSegment",
    "SUPPORTED_MIME_TYPES",
    "parse_document",
]
