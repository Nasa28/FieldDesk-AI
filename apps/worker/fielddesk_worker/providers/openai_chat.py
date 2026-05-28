from __future__ import annotations

import json
import time

import httpx

from fielddesk_worker.providers.base import CallMetrics


PROVIDER_NAME = "openai"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

# Pricing per 1M tokens, USD. Same table as openai_llm.py — kept duplicated
# rather than imported because the extraction provider lives on a separately
# evolving model+price cadence than the synthesis provider (we may move
# extraction to gpt-4.1 and keep synthesis on gpt-4o-mini for cost).
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


class OpenAIChatJSONProvider:
    """Implements LLMProvider.complete_json against OpenAI chat completions.

    Why a thin custom client and not the official SDK: the rest of the worker
    uses httpx with explicit timeouts and we log every call ourselves
    (AGENTS.md). The SDK adds two layers (retries we don't want, error
    classes we don't read) without giving us anything we can't get from a
    direct call. Mirrors the shape of OpenAIExtractionProvider on purpose so
    the two can move in lockstep.
    """

    name = PROVIDER_NAME

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

    @property
    def model(self) -> str:
        return self._model

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict,
        model: str | None = None,
    ) -> tuple[dict, CallMetrics]:
        """Call chat-completions with response_format=json_object.

        The `schema` argument is accepted for the LLMProvider Protocol but is
        used only as documentation here — the actual schema enforcement
        happens via pydantic validation in the caller (see
        recommendations/service.py). OpenAI's json_schema response format
        is available but the validation point belongs in the caller anyway
        so the same code path works against the stub.
        """
        effective_model = model or self._model
        body = {
            "model": effective_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
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
        duration_ms = int((time.perf_counter() - started) * 1000)
        r.raise_for_status()
        resp = r.json()

        choice = (resp.get("choices") or [{}])[0]
        raw_text = (choice.get("message") or {}).get("content") or ""
        usage = resp.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))

        cost_usd = round(
            input_tokens * COST_PER_1M_INPUT_USD.get(effective_model, 0.0) / 1_000_000
            + output_tokens * COST_PER_1M_OUTPUT_USD.get(effective_model, 0.0) / 1_000_000,
            6,
        )

        try:
            parsed = json.loads(raw_text)
            if not isinstance(parsed, dict):
                parsed = {}
        except json.JSONDecodeError:
            parsed = {}

        metrics = CallMetrics(
            provider=PROVIDER_NAME,
            model=effective_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            success=True,
        )
        # The schema param is unused at the wire level (validation is the
        # caller's job); referencing it once silences linters that flag it.
        _ = schema
        return parsed, metrics
