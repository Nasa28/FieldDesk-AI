from __future__ import annotations

import json
from typing import Any

from fielddesk_worker.providers.base import ExtractionResult


PROVIDER_NAME = "stub"
DEFAULT_MODEL = "stub-extractor-v1"

_STUB_PAYLOAD: dict[str, Any] = {
    "customer_name": "Jane Doe",
    "customer_phone": "555-0100",
    "service_address": "742 Evergreen Terrace",
    "trade_type": "plumbing",
    "issue_summary": "Leaking water heater",
    "detailed_description": (
        "Customer reports a water heater leaking in the basement. Requests a "
        "visit tomorrow morning. Mentions a 5-year warranty."
    ),
    "priority": "high",
    "preferred_visit_time": "tomorrow morning",
    "required_skills": ["plumbing"],
    "suggested_parts": ["water heater drain valve"],
    "safety_concerns": ["standing water near electrical panel"],
    "warranty_mentioned": True,
    "follow_up_questions": ["confirm water heater make and model"],
    "confidence": 0.92,
    "human_review_required": False,
    "human_review_reason": None,
}


class StubLLMExtractionProvider:
    def __init__(self, model: str = DEFAULT_MODEL):
        self._model = model

    def extract_ticket(self, transcript_text: str, context: dict[str, Any]) -> ExtractionResult:
        payload = dict(_STUB_PAYLOAD)
        raw_text = json.dumps(payload)
        return ExtractionResult(
            raw_text=raw_text,
            parsed_json=payload,
            provider=PROVIDER_NAME,
            model=self._model,
            duration_ms=0,
            input_tokens=max(1, len(transcript_text) // 4),
            output_tokens=len(raw_text) // 4,
            cost_usd=0.0,
            confidence=float(payload["confidence"]),
            metadata={
                "transcript_chars": len(transcript_text),
                "context_keys": sorted(context.keys()),
            },
        )
