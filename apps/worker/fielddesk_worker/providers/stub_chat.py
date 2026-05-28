from __future__ import annotations

from fielddesk_worker.providers.base import CallMetrics


PROVIDER_NAME = "stub"
DEFAULT_MODEL = "stub-chat-v1"


class StubChatJSONProvider:
    """Deterministic LLMProvider.complete_json used in tests + LLM_PROVIDER=stub.

    Returns a fixed-shape recommendations payload that's good enough to
    exercise the persistence path, pydantic validation, and UI rendering
    without spending real money. Eval runs that need to test prompt
    behavior use the OpenAI provider directly."""

    name = PROVIDER_NAME

    def __init__(self, model: str = DEFAULT_MODEL):
        self._model = model

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
        effective_model = model or self._model
        # Length-derived metrics so the budget/log paths get realistic-ish
        # numbers even with a stub, but cost is always 0.
        input_tokens = max(1, (len(system) + len(user)) // 4)
        payload: dict = {
            "possible_diagnosis": "Likely a worn supply hose at the shut-off valve.",
            "suggested_parts": ["copper p-trap", "1/2-inch supply line"],
            "safety_checklist": [
                "Confirm water main shut-off is accessible",
                "Verify floor area is dry before energizing nearby outlets",
            ],
            "follow_up_questions": [
                "When did the leak start?",
                "Has any visible damage extended to drywall?",
            ],
            "citations": [{"chunk_id": "stub-chunk-1", "note": "Common parts reference."}],
            "confidence": 0.78,
            "insufficient_context": False,
            "notes": None,
        }
        # `schema` is documentation here — validation happens in the caller.
        _ = schema
        metrics = CallMetrics(
            provider=PROVIDER_NAME,
            model=effective_model,
            input_tokens=input_tokens,
            output_tokens=len(str(payload)) // 4,
            duration_ms=0,
            cost_usd=0.0,
            success=True,
        )
        return payload, metrics
