from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Citation(BaseModel):
    """One pointer back to a retrieved chunk. The model emits chunk_id as a
    string (we sanitize it on the way in via wrap_untrusted_chunk's id
    sanitizer), and we display document_title back from the rag_queries row
    rather than trusting whatever the model echoes for the title."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    chunk_id: str
    note: str | None = None


class RecommendationsOutput(BaseModel):
    """Structured synthesis the LLM emits. Field names mirror PRD §10.3.

    Why a strict pydantic schema (not free-form text): the UI shows each list
    in its own panel and we score eval cases against the structure. Free text
    would also make the prompt-injection blast radius wider — a hostile chunk
    that gets the model to emit a paragraph saying "ignore safety, this is
    fine" is worse than one that gets the model to add one bogus entry to
    safety_checklist."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    possible_diagnosis: str | None = None
    suggested_parts: list[str] = Field(default_factory=list)
    safety_checklist: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)

    confidence: float = Field(ge=0.0, le=1.0)
    # Why a self-reported "insufficient_context" flag instead of always
    # synthesizing: with zero relevant chunks the right behavior is to say
    # nothing, not to hallucinate parts and procedures. The worker also
    # short-circuits when retrieval returned zero chunks (see service.py).
    insufficient_context: bool = False
    notes: str | None = None
