"""Phase 4.5 — RAG synthesis layer.

The `draft_ticket` job type, post-Phase 4.5, takes a ticket + the rag_queries
row produced by the preceding `rag` job and synthesizes structured
recommendations (possible diagnosis, suggested parts, safety checklist,
follow-up questions, citations to the retrieved chunks). Output is stored in
`ticket_recommendations`.

This is the highest-injection-risk LLM call in the system: the prompt ingests
tenant-uploaded document content. The chunk-wrapping helpers in
`prompting.safety` exist for exactly this call; see RECS_SYSTEM_PROMPT in
service.py for the hardening rules that match the AGENTS.md "Prompt injection"
section.
"""
