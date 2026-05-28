from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TradeType(StrEnum):
    PLUMBING = "plumbing"
    HVAC = "hvac"
    ELECTRICAL = "electrical"
    ROOFING = "roofing"
    GENERAL = "general"
    UNKNOWN = "unknown"


class TicketExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    customer_name: str | None = None
    customer_phone: str | None = None
    service_address: str | None = None
    trade_type: TradeType = TradeType.UNKNOWN
    issue_summary: str | None = None
    detailed_description: str | None = None
    priority: Priority = Priority.NORMAL
    preferred_visit_time: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    suggested_parts: list[str] = Field(default_factory=list)
    safety_concerns: list[str] = Field(default_factory=list)
    warranty_mentioned: bool = False
    follow_up_questions: list[str] = Field(default_factory=list)

    confidence: float = Field(ge=0.0, le=1.0)
    human_review_required: bool = False
    human_review_reason: str | None = None
