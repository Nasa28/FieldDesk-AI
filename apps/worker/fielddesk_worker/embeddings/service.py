from __future__ import annotations

from typing import Any


# TODO: chunk, embed, insert into document_chunks, log ai_model_calls.
def embed(job: dict[str, Any], cur) -> dict[str, Any]:
    return {"stub": True, "job_id": str(job.get("id")), "chunks": 0}


def chunk_text(text: str, target_tokens: int = 800, overlap_tokens: int = 100) -> list[str]:
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
