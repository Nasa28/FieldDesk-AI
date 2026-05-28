from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _FakeResponse:
    def __init__(self, *, embedding_dims: int):
        self._embedding_dims = embedding_dims

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "data": [{"index": 0, "embedding": [0.0] * self._embedding_dims}],
            "usage": {"prompt_tokens": 4},
        }


class _FakeClient:
    payloads: list[dict] = []
    embedding_dims = 1536

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers, json):
        self.payloads.append(json)
        return _FakeResponse(embedding_dims=self.embedding_dims)


sys.modules.setdefault("httpx", types.SimpleNamespace(Client=_FakeClient))

try:
    from fielddesk_worker.providers import openai_embedding
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"worker dependencies are not installed: {exc.name}") from exc

openai_embedding.httpx = types.SimpleNamespace(Client=_FakeClient)


class OpenAIEmbeddingProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeClient.payloads = []
        _FakeClient.embedding_dims = 1536

    def test_requests_1536_dimensions_for_text_embedding_3_models(self) -> None:
        provider = openai_embedding.OpenAIEmbeddingProvider(
            api_key="test-key",
            model="text-embedding-3-large",
        )

        vectors, metrics = provider.embed(["pump manual"])

        self.assertEqual(len(vectors), 1)
        self.assertEqual(len(vectors[0]), 1536)
        self.assertEqual(metrics.input_tokens, 4)
        self.assertEqual(_FakeClient.payloads[0]["dimensions"], 1536)

    def test_rejects_unexpected_embedding_dimensions(self) -> None:
        _FakeClient.embedding_dims = 3
        provider = openai_embedding.OpenAIEmbeddingProvider(api_key="test-key")

        with self.assertRaisesRegex(RuntimeError, "expected 1536"):
            provider.embed(["pump manual"])


if __name__ == "__main__":
    unittest.main()
