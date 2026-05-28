FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps for document parsing:
#   tesseract-ocr (+ eng language data) — OCR fallback for scanned PDFs.
#     Invoked by pytesseract; rendering of PDF pages to images happens
#     in-process via pypdfium2 (no poppler dep needed).
#   libreoffice-core + libreoffice-writer — headless .doc → .docx
#     conversion. The minimal subset of the libreoffice suite that
#     supports Writer's import filters. Adds ~400MB to the image; the
#     alternative pure-Python parsers for the .doc OLE binary format
#     are all either incomplete or unmaintained.
# fonts-liberation gives libreoffice + tesseract usable fonts so
# converted output doesn't render as tofu rectangles.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libreoffice-core \
        libreoffice-writer \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY apps/worker/pyproject.toml ./
COPY apps/worker/fielddesk_worker ./fielddesk_worker
COPY scripts/eval.sh ./scripts/eval.sh
RUN chmod +x ./scripts/eval.sh && pip install --upgrade pip && pip install .

CMD ["fielddesk-worker"]
