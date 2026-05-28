"""Document chunking and embedding service."""

from __future__ import annotations

from typing import Any


def embed(job: dict[str, Any]) -> dict[str, Any]:
    """Chunk + embed a document. Placeholder implementation."""
    # TODO:
    #   1. Load document by id, stream from object storage.
    #   2. Chunk by ~800 tokens with overlap.
    #   3. Call embeddings provider.
    #   4. Insert into document_chunks with pgvector embedding.
    #   5. Log ai_model_calls.
    return {"status": "succeeded", "chunks": 0, "stub": True}


def chunk_text(text: str, target_tokens: int = 800, overlap_tokens: int = 100) -> list[str]:
    """Naive character-based chunker; replace with a tokenizer-aware version."""
    if not text:
        return []
    approx_chars = target_tokens * 4
    overlap_chars = overlap_tokens * 4
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + approx_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap_chars
    return chunks
