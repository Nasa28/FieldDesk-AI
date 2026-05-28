from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable

from fielddesk_worker.parsing import ParsedSegment


# Default target / overlap pulled from the mid-2026 research synthesis:
# 512 tokens with ~12% overlap is the production-default for technical
# corpora with structured headings. Smaller chunks lose context, larger
# chunks blur embeddings.
DEFAULT_TARGET_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 64
# Hard cap: text-embedding-3-small accepts 8192 tokens per input, but
# embedding quality degrades well before that. Refuse anything above this
# and split harder.
MAX_TOKENS_PER_CHUNK = 1024


@dataclass(slots=True)
class Chunk:
    """One ready-to-embed chunk. content_hash gives the worker idempotency:
    re-ingesting the same document produces the same hashes for unchanged
    sections, so the partial UNIQUE (document_id, content_hash) index in
    migration 00017 quietly drops re-inserts of identical content."""

    text: str
    chunk_index: int
    token_count: int
    content_hash: str
    heading_path: list[str] = field(default_factory=list)
    source_page: int | None = None
    source_locator: dict = field(default_factory=dict)


# tiktoken's cl100k_base is the encoding for text-embedding-3-*. We resolve
# the encoder lazily so the chunker is importable even when tiktoken isn't
# installed (test environments, lint passes).
_ENCODING_NAME = "cl100k_base"
_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        try:
            import tiktoken

            _encoder = tiktoken.get_encoding(_ENCODING_NAME)
        except ImportError as e:
            raise RuntimeError(
                "tiktoken is required for chunking; install the worker deps"
            ) from e
    return _encoder


def _count_tokens(text: str) -> int:
    return len(_get_encoder().encode(text))


def _encode(text: str) -> list[int]:
    return _get_encoder().encode(text)


def _decode(tokens: list[int]) -> str:
    return _get_encoder().decode(tokens)


# Recursive splitter separators in priority order. Borrowed from LangChain's
# RecursiveCharacterTextSplitter shape because the heuristic genuinely works:
# prefer splitting on the largest semantic boundary that's still under the
# token budget. We're not pulling in LangChain — just the idea.
_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]


def chunk_segments(
    segments: Iterable[ParsedSegment],
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Split ParsedSegment instances into token-budgeted chunks.

    Each chunk inherits the segment's heading_path / source_page /
    source_locator so the citation survives the split. A segment short
    enough to fit in one chunk becomes one chunk. A segment too long gets
    recursively split on the highest-priority separator that produces
    pieces under the budget, with overlap_tokens of tail-to-head shared
    between adjacent chunks.
    """
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be in [0, target_tokens)")

    chunks: list[Chunk] = []
    index = 0
    for segment in segments:
        for body in _split_to_budget(segment.text, target_tokens):
            for windowed in _apply_overlap(body, target_tokens, overlap_tokens):
                chunks.append(
                    Chunk(
                        text=windowed,
                        chunk_index=index,
                        token_count=_count_tokens(windowed),
                        content_hash=_hash(
                            windowed, segment.heading_path, segment.source_page
                        ),
                        heading_path=list(segment.heading_path),
                        source_page=segment.source_page,
                        source_locator=dict(segment.source_locator),
                    )
                )
                index += 1
    return chunks


def _split_to_budget(text: str, target_tokens: int) -> list[str]:
    """Yield pieces each <= target_tokens by recursively trying separators."""
    if not text.strip():
        return []
    if _count_tokens(text) <= target_tokens:
        return [text]

    pieces = _recursive_split(text, _SEPARATORS, target_tokens)
    return [p for p in pieces if p.strip()]


def _recursive_split(text: str, separators: list[str], target_tokens: int) -> list[str]:
    if _count_tokens(text) <= target_tokens:
        return [text]
    if not separators:
        # No more separators to try — fall back to hard-splitting by token
        # ids so we don't return a single oversized chunk. This is the
        # safety net for pathological inputs (e.g. a 5kb URL with no spaces).
        return _hard_split_by_tokens(text, target_tokens)
    separator, *rest = separators
    if separator == "":
        return _hard_split_by_tokens(text, target_tokens)
    parts = text.split(separator)
    if len(parts) == 1:
        return _recursive_split(text, rest, target_tokens)

    # Greedy merge: walk the parts and accumulate into pieces under budget.
    out: list[str] = []
    current = ""
    glue = separator
    for part in parts:
        candidate = part if not current else current + glue + part
        if _count_tokens(candidate) <= target_tokens:
            current = candidate
            continue
        if current:
            out.append(current)
        # The next part might itself be over budget — recurse on it.
        if _count_tokens(part) > target_tokens:
            out.extend(_recursive_split(part, rest, target_tokens))
            current = ""
        else:
            current = part
    if current:
        out.append(current)
    return out


def _hard_split_by_tokens(text: str, target_tokens: int) -> list[str]:
    tokens = _encode(text)
    pieces: list[str] = []
    for i in range(0, len(tokens), target_tokens):
        pieces.append(_decode(tokens[i : i + target_tokens]))
    return pieces


def _apply_overlap(text: str, target_tokens: int, overlap_tokens: int) -> list[str]:
    """Add overlap_tokens of the previous chunk's tail to the head of the next.

    For most chunks the input is already <= target_tokens so this is a no-op
    (returns [text]). For chunks that came out of a recursive split, sliding
    window across the encoded tokens with stride = target - overlap gives the
    overlap the retrieval literature recommends.
    """
    if overlap_tokens == 0:
        return [text]
    tokens = _encode(text)
    if len(tokens) <= target_tokens:
        return [text]
    stride = target_tokens - overlap_tokens
    out: list[str] = []
    i = 0
    while i < len(tokens):
        window = tokens[i : i + target_tokens]
        if not window:
            break
        out.append(_decode(window))
        if i + target_tokens >= len(tokens):
            break
        i += stride
    return out


def _hash(text: str, heading_path: list[str], source_page: int | None) -> str:
    """SHA-256 of (text + heading_path + source_page) — locator metadata is
    included so the same text appearing on two different pages doesn't
    accidentally dedupe to a single chunk."""
    h = hashlib.sha256()
    h.update(text.encode("utf-8"))
    h.update(b"\x00")
    h.update("/".join(heading_path).encode("utf-8"))
    h.update(b"\x00")
    h.update(str(source_page if source_page is not None else "").encode("utf-8"))
    return h.hexdigest()


# Backwards-compat shim: the pre-Phase-4 embed stub exported a `chunk_text`
# function with a character-count signature. Nothing imports it anymore, but
# keep a thin shim so any old call sites surface clearly.
def chunk_text(text: str, target_tokens: int = DEFAULT_TARGET_TOKENS,
               overlap_tokens: int = DEFAULT_OVERLAP_TOKENS) -> list[str]:
    chunks = chunk_segments(
        [ParsedSegment(text=text)],
        target_tokens=target_tokens,
        overlap_tokens=overlap_tokens,
    )
    return [c.text for c in chunks]
