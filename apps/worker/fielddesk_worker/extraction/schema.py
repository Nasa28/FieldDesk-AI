"""Structured extraction schema for a job ticket.

This is the contract the LLM must produce. Invalid output never creates a
final ticket — it goes to the human review queue.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TradeType(StrEnum):
    PLUMBING = "plumbing"
    HVAC = "hvac"
    ELECTRICAL = "electrical"
    APPLIANCE = "appliance"
    GENERAL = "general"
    OTHER = "other"


class TicketExtraction(BaseModel):
    customer_name: str | None = None
    customer_phone: str | None = None
    service_address: str | None = None
    trade_type: TradeType | None = None
    issue_summary: str | None = None
    detailed_description: str | None = None
    priority: Priority | None = None
    preferred_visit_time: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    suggested_parts: list[str] = Field(default_factory=list)
    safety_concerns: list[str] = Field(default_factory=list)
    warranty_mention: bool | None = None
    follow_up_questions: list[str] = Field(default_factory=list)

    confidence: float = Field(ge=0.0, le=1.0)
    human_review_required: bool
