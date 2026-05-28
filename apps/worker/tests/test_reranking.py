from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_MISSING = object()
_SAVED_MODULES = {
    name: sys.modules.get(name, _MISSING)
    for name in (
        "structlog",
        "fielddesk_worker.config",
        "fielddesk_worker.db_queries",
        "httpx",
    )
}

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
        load_settings=lambda: types.SimpleNamespace(rerank_overrequest=20)
    ),
)
sys.modules.setdefault(
    "fielddesk_worker.db_queries",
    types.SimpleNamespace(hybrid_search=lambda *args, **kwargs: []),
)
sys.modules.setdefault(
    "httpx",
    types.SimpleNamespace(
        RequestError=Exception,
        post=lambda *args, **kwargs: None,
    ),
)

try:
    from fielddesk_worker.rag import retrieval
    from fielddesk_worker.reranking import service as reranker_service
    from fielddesk_worker.reranking.base import RerankedHit, RerankerMetrics
    from fielddesk_worker.reranking.cohere import CohereReranker
    from fielddesk_worker.reranking.noop import NoopReranker
    from fielddesk_worker.reranking.voyage import VoyageReranker
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"worker dependencies are not installed: {exc.name}") from exc
finally:
    for _name, _module in _SAVED_MODULES.items():
        if _module is _MISSING:
            sys.modules.pop(_name, None)
        else:
            sys.modules[_name] = _module


class _FakeReranker:
    name = "fake"
    model = "fake-rerank"

    def __init__(self, *, success: bool = True):
        self.success = success
        self.documents: list[str] = []
        self.top_n: int | None = None

    def is_noop(self) -> bool:
        return False

    def rerank(
        self, *, query: str, documents: list[str], top_n: int
    ) -> tuple[list[RerankedHit], RerankerMetrics]:
        del query
        self.documents = documents
        self.top_n = top_n
        metrics = RerankerMetrics(
            provider=self.name,
            model=self.model,
            duration_ms=7,
            success=self.success,
            cost_usd=0.001,
            candidate_count=len(documents),
        )
        if not self.success:
            return [], metrics
        return [RerankedHit(index=1, relevance_score=0.99)], metrics


class _NoopReranker:
    name = "none"
    model = "noop"

    def is_noop(self) -> bool:
        return True

    def rerank(self, *, query: str, documents: list[str], top_n: int):
        raise AssertionError("noop reranker should not be called")


def _rows() -> list[dict]:
    return [
        {"chunk_id": "c1", "text": "first chunk"},
        {"chunk_id": "c2", "text": "second chunk"},
    ]


class RetrievalRerankTests(unittest.TestCase):
    def test_uses_text_column_and_caps_overrequest(self) -> None:
        calls: list[int] = []

        def fake_hybrid_search(*args, **kwargs):
            del args
            calls.append(kwargs["top_k"])
            return _rows()

        reranker = _FakeReranker()
        settings = types.SimpleNamespace(rerank_overrequest=10_000)
        with (
            patch.object(retrieval, "hybrid_search", side_effect=fake_hybrid_search),
            patch.object(retrieval, "load_settings", return_value=settings),
        ):
            results, metrics = retrieval.retrieve_with_optional_rerank(
                object(),
                tenant_id="tenant-1",
                query_text="pump warranty",
                embedding_literal="[0.1]",
                top_k=5,
                reranker=reranker,
            )

        self.assertEqual(calls, [retrieval.MAX_RERANK_CANDIDATES])
        self.assertEqual(reranker.documents, ["first chunk", "second chunk"])
        self.assertEqual(reranker.top_n, 5)
        self.assertTrue(metrics and metrics.success)
        self.assertEqual([r["chunk_id"] for r in results], ["c2"])
        self.assertEqual(results[0]["rerank_score"], 0.99)

    def test_failed_rerank_falls_back_to_hybrid_order(self) -> None:
        def fake_hybrid_search(*args, **kwargs):
            del args
            return _rows()

        settings = types.SimpleNamespace(rerank_overrequest=20)
        with (
            patch.object(retrieval, "hybrid_search", side_effect=fake_hybrid_search),
            patch.object(retrieval, "load_settings", return_value=settings),
        ):
            results, metrics = retrieval.retrieve_with_optional_rerank(
                object(),
                tenant_id="tenant-1",
                query_text="pump warranty",
                embedding_literal="[0.1]",
                top_k=1,
                reranker=_FakeReranker(success=False),
            )

        self.assertFalse(metrics and metrics.success)
        self.assertEqual([r["chunk_id"] for r in results], ["c1"])

    def test_noop_path_caps_top_k(self) -> None:
        calls: list[int] = []

        def fake_hybrid_search(*args, **kwargs):
            del args
            calls.append(kwargs["top_k"])
            return _rows()

        with patch.object(retrieval, "hybrid_search", side_effect=fake_hybrid_search):
            results, metrics = retrieval.retrieve_with_optional_rerank(
                object(),
                tenant_id="tenant-1",
                query_text="pump warranty",
                embedding_literal="[0.1]",
                top_k=999,
                reranker=_NoopReranker(),
            )

        self.assertEqual(calls, [retrieval.MAX_RERANK_CANDIDATES])
        self.assertIsNone(metrics)
        self.assertEqual(len(results), 2)


class _MalformedResponse:
    status_code = 200
    text = "not json"

    def json(self):
        raise ValueError("bad json")


class RerankerProviderParsingTests(unittest.TestCase):
    def test_voyage_malformed_success_response_returns_failed_metrics(self) -> None:
        provider = VoyageReranker(api_key="test-key")
        fake_httpx = types.SimpleNamespace(
            post=lambda *args, **kwargs: _MalformedResponse()
        )

        with patch.object(sys.modules[VoyageReranker.__module__], "httpx", fake_httpx):
            hits, metrics = provider.rerank(
                query="q",
                documents=["doc"],
                top_n=1,
            )

        self.assertEqual(hits, [])
        self.assertFalse(metrics.success)
        self.assertEqual(metrics.error_class, "ValueError")

    def test_cohere_malformed_success_response_returns_failed_metrics(self) -> None:
        provider = CohereReranker(api_key="test-key")
        fake_httpx = types.SimpleNamespace(
            post=lambda *args, **kwargs: _MalformedResponse()
        )

        with patch.object(sys.modules[CohereReranker.__module__], "httpx", fake_httpx):
            hits, metrics = provider.rerank(
                query="q",
                documents=["doc"],
                top_n=1,
            )

        self.assertEqual(hits, [])
        self.assertFalse(metrics.success)
        self.assertEqual(metrics.error_class, "ValueError")


class RerankerFactoryTests(unittest.TestCase):
    def test_none_provider_returns_noop(self) -> None:
        settings = types.SimpleNamespace(rerank_provider="none")

        with patch.object(reranker_service, "load_settings", return_value=settings):
            reranker = reranker_service.make_reranker()

        self.assertIsInstance(reranker, NoopReranker)

    def test_voyage_provider_maps_non_voyage_model_to_lite_default(self) -> None:
        settings = types.SimpleNamespace(
            rerank_provider="voyage",
            voyage_api_key="voyage-key",
            cohere_api_key=None,
            rerank_model="rerank-v3.5",
        )

        with patch.object(reranker_service, "load_settings", return_value=settings):
            reranker = reranker_service.make_reranker()

        self.assertIsInstance(reranker, VoyageReranker)
        self.assertEqual(reranker.model, "rerank-2.5-lite")

    def test_cohere_provider_maps_non_cohere_model_to_cohere_default(self) -> None:
        settings = types.SimpleNamespace(
            rerank_provider="cohere",
            voyage_api_key=None,
            cohere_api_key="cohere-key",
            rerank_model="rerank-2.5-lite",
        )

        with patch.object(reranker_service, "load_settings", return_value=settings):
            reranker = reranker_service.make_reranker()

        self.assertIsInstance(reranker, CohereReranker)
        self.assertEqual(reranker.model, "rerank-v3.5")


if __name__ == "__main__":
    unittest.main()
