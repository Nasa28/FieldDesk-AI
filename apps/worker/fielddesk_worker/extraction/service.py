"""Structured extraction service.

Takes a transcript and produces a validated TicketExtraction. Invalid or
low-confidence outputs route to human review rather than creating a ticket.
"""

from __future__ import annotations

from typing import Any


def extract(job: dict[str, Any]) -> dict[str, Any]:
    """Run an extraction job. Placeholder implementation."""
    # TODO:
    #   1. Load transcript by id.
    #   2. Call LLM with structured-output schema.
    #   3. Validate against TicketExtraction.
    #   4. Compute confidence + human_review_required.
    #   5. Insert into ai_extractions + log ai_model_calls.
    #   6. Enqueue rag + draft_ticket jobs.
    return {"status": "succeeded", "extraction_id": None, "stub": True}


def draft_ticket(job: dict[str, Any]) -> dict[str, Any]:
    """Materialize a draft job_ticket row from an extraction."""
    # TODO: copy fields from ai_extractions into job_tickets with status=draft.
    return {"status": "succeeded", "ticket_id": None, "stub": True}
