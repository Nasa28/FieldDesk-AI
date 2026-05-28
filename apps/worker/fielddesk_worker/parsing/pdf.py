from __future__ import annotations

import io

from fielddesk_worker.parsing.base import ParseError, ParsedSegment


# OCR is slow and CPU-bound, so we only invoke it when text extraction has
# returned nothing — text-native PDFs are 10-100x faster and more accurate.
# 200 DPI is the sweet spot: tesseract's per-character accuracy plateaus
# around 150-200 for typical office documents, and going higher mostly
# burns CPU. Renders go through pypdfium2 which ships a self-contained
# wheel (no poppler dep); OCR itself needs the tesseract system binary
# (installed in worker.Dockerfile).
_OCR_RENDER_DPI = 200


def parse_pdf(content: bytes) -> list[ParsedSegment]:
    """Text-native PDF parser with scanned-PDF fallback to Tesseract OCR.

    Strategy:
      1. Try text extraction first via pypdf. Most PDFs (manuals, exports
         from Word, anything generated digitally) succeed here and OCR
         never runs.
      2. If text extraction yields nothing on a PDF that has pages, fall
         back to per-page Tesseract OCR. This covers the scanned-document
         case that the old branch raised ParseError for.

    Out of scope: encrypted PDFs (raise ParseError with an actionable
    message asking the operator to remove the password), table extraction
    (would need a separate library + schema for cell-level chunks).

    The OCR fallback adds page-level source_locator markers with
    `"ocr": true` so citations can later display "OCR'd page 4" when we
    surface the provenance to operators — useful for explaining lower
    confidence on scanned source documents.
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
        raise ParseError(
            "PDF is password-protected; remove the password and re-upload, "
            "or upload an unencrypted version"
        )

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
        # scanned PDF. Try OCR before giving up.
        segments = _ocr_pdf_pages(content, page_count)
        if not segments:
            # OCR ran but produced no text either: pages are likely blank
            # scans, a corrupt-but-parseable PDF, or a non-Latin script
            # tesseract isn't trained for. Fail loudly rather than land
            # 'ready' with zero chunks.
            raise ParseError(
                f"no extractable text in {page_count}-page PDF "
                "(text extraction empty and OCR returned no text either; "
                "blank scans or unsupported script)"
            )
    return segments


def _ocr_pdf_pages(content: bytes, page_count: int) -> list[ParsedSegment]:
    """Render each page with pypdfium2 and OCR it with Tesseract.

    Both deps are imported lazily so a text-only PDF never pays the import
    cost (pypdfium2 is ~15MB of C extension at first import). A missing
    system tesseract binary raises ParseError with an actionable message
    — better than the generic TesseractNotFoundError that confuses
    operators reading the failures dashboard.
    """
    try:
        import pypdfium2 as pdfium
        import pytesseract
        from pytesseract import TesseractNotFoundError
    except ImportError as e:
        raise ParseError(
            f"OCR fallback requires pypdfium2 and pytesseract: {e}"
        ) from e

    scale = _OCR_RENDER_DPI / 72.0
    pdf = pdfium.PdfDocument(content)
    # If pypdfium2 disagrees with pypdf on page count (malformed PDF,
    # different decoders), trust pypdfium2 for the OCR loop since that's
    # what we're rendering. of_pages in the locator stays as the pypdf
    # count so it matches what the text-path would have reported.
    pages_to_render = len(pdf)
    segments: list[ParsedSegment] = []
    for index in range(pages_to_render):
        page = pdf[index]
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        try:
            text = pytesseract.image_to_string(image, lang="eng")
        except TesseractNotFoundError as e:
            raise ParseError(
                "OCR requires the tesseract system binary "
                "(install tesseract-ocr in the worker image): " + str(e)
            ) from e
        text = (text or "").strip()
        if not text:
            continue
        segments.append(
            ParsedSegment(
                text=text,
                source_page=index + 1,
                source_locator={
                    "page": index + 1,
                    "of_pages": page_count,
                    "ocr": True,
                },
            )
        )
    return segments
