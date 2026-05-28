from __future__ import annotations

import json
import time
from typing import Any

import httpx

from fielddesk_worker.prompting import wrap_untrusted_transcript
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


# The system prompt body lives in the prompts/ registry now (Phase 5). This
# constant is the v1 body, re-derived once at import so existing call sites
# (tests, anyone grepping for "EXTRACTION_SYSTEM_PROMPT") still work
# unchanged. Edit the registry, not this line.
from fielddesk_worker.prompts import get_extraction_prompt

EXTRACTION_SYSTEM_PROMPT = get_extraction_prompt()


def _build_extraction_user_content(transcript_text: str) -> str:
    # Delegates to the shared prompting/safety helper. Keep the function name
    # so existing tests / call sites continue to work; the actual delimiter +
    # HTML-escape policy lives in one place now (apps/.../prompting/safety.py)
    # so future LLM calls (RAG synthesis, draft_ticket) inherit it.
    return wrap_untrusted_transcript(transcript_text)


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

    def extract_ticket(
        self,
        transcript_text: str,
        context: dict[str, Any],
        *,
        system_prompt: str | None = None,
    ) -> ExtractionResult:
        # Default kwarg keeps every existing caller (extraction/service.py,
        # current eval pipeline) unchanged. Phase 5 prompt-version
        # comparison passes a different body to A/B against v1.
        prompt = system_prompt or EXTRACTION_SYSTEM_PROMPT
        user_content = _build_extraction_user_content(transcript_text)
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": prompt},
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
