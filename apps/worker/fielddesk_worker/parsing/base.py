from __future__ import annotations

from dataclasses import dataclass, field


# Mapping from supported mime type to parser key. The Go upload handler
# validates against the same set (apps/api/internal/handlers/documents.go).
# Keep them in sync when extending.
SUPPORTED_MIME_TYPES: dict[str, str] = {
    "text/plain": "text",
    "text/markdown": "markdown",
    "text/x-markdown": "markdown",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/msword": "doc",
}


class ParseError(RuntimeError):
    """Raised when a document is structurally unparseable.

    A ParseError lands the document in status='failed' with parse_error set.
    Do not raise ParseError for "the document was empty after extraction" —
    that's a legitimate-but-empty document and should produce zero chunks.
    """


@dataclass(slots=True)
class ParsedSegment:
    """One pre-chunk segment emitted by a parser.

    `text` is the raw content of the segment (a markdown section, a PDF page,
    a DOCX section between headings). The chunker is responsible for splitting
    further on token budgets; the parser's job is to preserve structure that
    the chunker would otherwise destroy (page boundaries, heading paths).
    """

    text: str
    heading_path: list[str] = field(default_factory=list)
    source_page: int | None = None
    # Generic JSON locator for anything we want to surface in citations later
    # (line ranges, table cells, slide numbers) without altering the schema.
    source_locator: dict = field(default_factory=dict)


def parse_document(content: bytes, mime_type: str) -> list[ParsedSegment]:
    """Route to the appropriate parser based on mime_type."""
    parser_key = SUPPORTED_MIME_TYPES.get(mime_type.lower())
    if parser_key is None:
        raise ParseError(f"unsupported mime_type: {mime_type}")
    # Local imports keep the optional heavy deps (pypdf, python-docx) out of
    # the import graph for plain-text ingest and out of test-only paths.
    if parser_key == "text":
        from fielddesk_worker.parsing.text import parse_text

        return parse_text(content)
    if parser_key == "markdown":
        from fielddesk_worker.parsing.markdown import parse_markdown

        return parse_markdown(content)
    if parser_key == "pdf":
        from fielddesk_worker.parsing.pdf import parse_pdf

        return parse_pdf(content)
    if parser_key == "docx":
        from fielddesk_worker.parsing.docx import parse_docx

        return parse_docx(content)
    if parser_key == "pptx":
        from fielddesk_worker.parsing.pptx import parse_pptx

        return parse_pptx(content)
    if parser_key == "doc":
        from fielddesk_worker.parsing.doc import parse_doc

        return parse_doc(content)
    raise ParseError(f"unimplemented parser: {parser_key}")
