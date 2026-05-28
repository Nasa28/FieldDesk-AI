from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_CALLS: list[dict] = []
_MISSING = object()
_SAVED_MODULES = {
    name: sys.modules.get(name, _MISSING)
    for name in (
        "structlog",
        "fielddesk_worker.config",
        "fielddesk_worker.db_queries",
    )
}


def _insert_model_call(cur, **kwargs):
    del cur
    _CALLS.append(kwargs)


sys.modules.setdefault(
    "structlog",
    types.SimpleNamespace(
        get_logger=lambda: types.SimpleNamespace(
            warning=lambda *args, **kwargs: None,
        )
    ),
)
sys.modules.setdefault(
    "fielddesk_worker.config",
    types.SimpleNamespace(
        load_settings=lambda: types.SimpleNamespace(
            llm_provider="stub",
            extraction_model="stub-chat-v1",
            openai_api_key="",
        )
    ),
)
sys.modules.setdefault(
    "fielddesk_worker.db_queries",
    types.SimpleNamespace(
        insert_model_call=_insert_model_call,
        log_model_call_isolated=lambda **kwargs: None,
    ),
)

try:
    from fielddesk_worker.rag.answer import synthesize_answer
except ModuleNotFoundError as exc:
    synthesize_answer = None
    _IMPORT_SKIP = f"worker dependencies are not installed: {exc.name}"
else:
    _IMPORT_SKIP = ""
finally:
    for _name, _module in _SAVED_MODULES.items():
        if _module is _MISSING:
            sys.modules.pop(_name, None)
        else:
            sys.modules[_name] = _module


class KnowledgeBaseAnswerTests(unittest.TestCase):
    def setUp(self) -> None:
        if _IMPORT_SKIP:
            self.skipTest(_IMPORT_SKIP)
        _CALLS.clear()

    def test_synthesizes_grounded_answer_from_chunks(self) -> None:
        answer = synthesize_answer(
            cur=object(),
            job={"id": "job-1"},
            tenant_id="tenant-1",
            query_text="What should I inspect?",
            rag_query_id="rag-1",
            chunks=[
                {
                    "chunk_id": "chunk-1",
                    "document_title": "Pump Manual",
                    "text": "Inspect the inlet strainer before replacing the pump.",
                }
            ],
        )

        self.assertIn("retrieved knowledge-base chunk", answer["answer"])
        self.assertEqual(answer["citations"][0]["chunk_id"], "chunk-1")
        self.assertFalse(answer["insufficient_context"])
        self.assertTrue(answer["json_valid"])
        self.assertEqual(answer["provider"], "stub")
        self.assertEqual(_CALLS[0]["kind"], "llm")
        self.assertEqual(_CALLS[0]["request_meta"]["purpose"], "kb_answer")

    def test_empty_retrieval_short_circuits_without_llm_call(self) -> None:
        answer = synthesize_answer(
            cur=object(),
            job={"id": "job-1"},
            tenant_id="tenant-1",
            query_text="What should I inspect?",
            rag_query_id="rag-1",
            chunks=[],
        )

        self.assertIsNone(answer["answer"])
        self.assertTrue(answer["insufficient_context"])
        self.assertEqual(answer["provider"], "none")
        self.assertEqual(_CALLS, [])


if __name__ == "__main__":
    unittest.main()
