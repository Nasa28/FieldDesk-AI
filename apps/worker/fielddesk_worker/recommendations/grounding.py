from __future__ import annotations

from typing import Any

from fielddesk_worker.recommendations.schema import RecommendationsOutput


def enforce_grounded_recommendations(
    output: RecommendationsOutput, chunks: list[dict[str, Any]]
) -> tuple[RecommendationsOutput, bool]:
    """Keep visible recommendations tied to retrieved chunks.

    The prompt asks the model to cite every recommendation, but prompt
    compliance is not a security boundary. Before persisting, filter citations
    down to chunk_ids that were actually in this retrieval set. If the model
    gave operator-facing advice without any surviving citation, degrade the
    advice to insufficient context rather than showing unsupported parts,
    safety items, or a diagnosis.
    """
    valid_chunk_ids = {
        str(chunk.get("chunk_id") or chunk.get("id"))
        for chunk in chunks
        if chunk.get("chunk_id") or chunk.get("id")
    }
    grounded_citations = [
        citation
        for citation in output.citations
        if citation.chunk_id in valid_chunk_ids
    ]
    citations_changed = len(grounded_citations) != len(output.citations)
    has_advice = bool(
        output.possible_diagnosis
        or output.suggested_parts
        or output.safety_checklist
    )
    if has_advice and not grounded_citations:
        return (
            output.model_copy(
                update={
                    "possible_diagnosis": None,
                    "suggested_parts": [],
                    "safety_checklist": [],
                    "citations": [],
                    "confidence": min(output.confidence, 0.2),
                    "insufficient_context": True,
                    "notes": _append_note(
                        output.notes,
                        (
                            "Model output contained recommendations without "
                            "citations from the retrieved chunks; advice was "
                            "suppressed."
                        ),
                    ),
                }
            ),
            False,
        )
    if citations_changed:
        return output.model_copy(update={"citations": grounded_citations}), False
    return output, True


def _append_note(existing: str | None, addition: str) -> str:
    if existing and existing.strip():
        return f"{existing.strip()} {addition}"
    return addition
