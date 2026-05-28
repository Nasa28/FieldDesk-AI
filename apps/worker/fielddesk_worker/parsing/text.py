from __future__ import annotations

from fielddesk_worker.parsing.base import ParseError, ParsedSegment


def parse_text(content: bytes) -> list[ParsedSegment]:
    """Plain-text parser. No structure; the chunker will split on token budget."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        # Fall back to latin-1 so a misdeclared mime_type doesn't ruin the whole
        # document; if it's truly binary we'll still produce something, and the
        # token-count cap in the chunker will prevent unbounded gibberish.
        try:
            text = content.decode("latin-1")
        except Exception as e:
            raise ParseError(f"could not decode text: {e}") from e
    text = text.strip()
    if not text:
        return []
    return [ParsedSegment(text=text)]
