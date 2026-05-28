from __future__ import annotations

import io

from fielddesk_worker.parsing.base import ParseError, ParsedSegment


def parse_pdf(content: bytes) -> list[ParsedSegment]:
    """Text-native PDF parser. Emits one segment per page so citations can
    say "page 4" even after chunking inside that page.

    Out of scope for v1: scanned PDFs (would need OCR), encrypted PDFs,
    table extraction. An encrypted PDF raises ParseError so the document
    lands in status='failed' with a clear reason — we don't silently drop
    content the operator asked us to index. Same for a PDF whose pages
    yield no extractable text at all: that's almost always a scanned
    document, and marking it 'ready' with zero chunks would be silent
    garbage from the operator's perspective.
    """
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as e:
        raise ParseError(f"pypdf is required for PDF parsing: {e}") from e

    try:
        reader = PdfReader(io.BytesIO(content))
    except PdfReadError as e:
        raise ParseError(f"could not read pdf: {e}") from e

    if reader.is_encrypted:
        raise ParseError("encrypted PDFs are not supported in v1")

    page_count = len(reader.pages)
    segments: list[ParsedSegment] = []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as e:  # noqa: BLE001
            raise ParseError(f"pypdf failed on page {index + 1}: {e}") from e
        text = text.strip()
        if not text:
            continue
        segments.append(
            ParsedSegment(
                text=text,
                source_page=index + 1,
                source_locator={"page": index + 1, "of_pages": page_count},
            )
        )

    if page_count > 0 and not segments:
        # Pages exist but no text extracted anywhere — overwhelmingly a
        # scanned PDF. OCR is out of scope for v1, so fail loudly rather
        # than land 'ready' with zero chunks.
        raise ParseError(
            f"no extractable text in {page_count}-page PDF; "
            "scanned PDFs require OCR which is not supported in v1"
        )
    return segments
