from __future__ import annotations

import json
import time
from typing import Any

import httpx

from fielddesk_worker.providers.base import ExtractionResult


PROVIDER_NAME = "openai"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

# Pricing per 1M tokens, USD. Extend the table as new models are added.
COST_PER_1M_INPUT_USD: dict[str, float] = {
    "gpt-4o-mini": 0.15,
    "gpt-4o": 2.50,
    "gpt-4.1-mini": 0.40,
    "gpt-4.1": 2.00,
}
COST_PER_1M_OUTPUT_USD: dict[str, float] = {
    "gpt-4o-mini": 0.60,
    "gpt-4o": 10.00,
    "gpt-4.1-mini": 1.60,
    "gpt-4.1": 8.00,
}


EXTRACTION_SYSTEM_PROMPT = """You extract structured field-service job-ticket details from a technician's voice-note transcript.

Return a SINGLE JSON object matching this schema EXACTLY (no prose, no markdown):
{
  "customer_name": string|null,
  "customer_phone": string|null,
  "service_address": string|null,
  "trade_type": "plumbing"|"hvac"|"electrical"|"roofing"|"general"|"unknown",
  "issue_summary": string|null,
  "detailed_description": string|null,
  "priority": "low"|"normal"|"high"|"urgent",
  "preferred_visit_time": string|null,
  "required_skills": string[],
  "suggested_parts": string[],
  "safety_concerns": string[],
  "warranty_mentioned": boolean,
  "follow_up_questions": string[],
  "confidence": number between 0 and 1,
  "human_review_required": boolean,
  "human_review_reason": string|null
}

Rules:
- Use null for fields you cannot confidently extract.
- "confidence" is your subjective certainty that the extraction is correct.
- Set "human_review_required": true and provide a short "human_review_reason" if any of:
    - critical fields are missing (address, issue_summary)
    - audio/transcript is ambiguous or contradictory
    - safety concerns are mentioned
    - sensitive customer or warranty disputes are mentioned
- Do not invent customer details that aren't in the transcript.
"""


class OpenAIExtractionProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 60.0,
    ):
        if not api_key:
            raise ValueError("OpenAI api_key is required")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def extract_ticket(self, transcript_text: str, context: dict[str, Any]) -> ExtractionResult:
        user_content = f"Transcript:\n{transcript_text}\n\nReturn the JSON object only."
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"

        started = time.perf_counter()
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(url, json=body, headers=headers)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        r.raise_for_status()
        resp = r.json()

        choice = (resp.get("choices") or [{}])[0]
        raw_text = (choice.get("message") or {}).get("content") or ""
        usage = resp.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))

        cost_usd = round(
            input_tokens * COST_PER_1M_INPUT_USD.get(self._model, 0.0) / 1_000_000
            + output_tokens * COST_PER_1M_OUTPUT_USD.get(self._model, 0.0) / 1_000_000,
            6,
        )

        try:
            parsed = json.loads(raw_text)
            if not isinstance(parsed, dict):
                parsed = {}
        except json.JSONDecodeError:
            parsed = {}

        confidence: float | None = None
        raw_conf = parsed.get("confidence") if isinstance(parsed, dict) else None
        if isinstance(raw_conf, (int, float)):
            confidence = float(raw_conf)

        return ExtractionResult(
            raw_text=raw_text,
            parsed_json=parsed,
            provider=PROVIDER_NAME,
            model=self._model,
            duration_ms=elapsed_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            confidence=confidence,
            metadata={
                "finish_reason": choice.get("finish_reason"),
                "response_id": resp.get("id"),
                "transcript_chars": len(transcript_text),
                "context_keys": sorted(context.keys()),
            },
        )
