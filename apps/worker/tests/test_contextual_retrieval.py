from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fielddesk_worker.embeddings.chunker import Chunk
    from fielddesk_worker.embeddings.contextual import build_retrieval_text
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"worker dependencies are not installed: {exc.name}") from exc


def _load_insert_chunk():
    missing = object()
    saved_modules = {
        name: sys.modules.get(name, missing)
        for name in ("psycopg", "psycopg.types", "psycopg.types.json")
    }
    try:
        try:
            import psycopg.types.json  # noqa: F401
        except ModuleNotFoundError:
            psycopg_mod = types.ModuleType("psycopg")
            types_mod = types.ModuleType("psycopg.types")
            json_mod = types.ModuleType("psycopg.types.json")

            class Jsonb:
                def __init__(self, value):
                    self.value = value

            json_mod.Jsonb = Jsonb
            sys.modules.setdefault("psycopg", psycopg_mod)
            sys.modules.setdefault("psycopg.types", types_mod)
            sys.modules.setdefault("psycopg.types.json", json_mod)

        module_path = (
            Path(__file__).resolve().parents[1]
            / "fielddesk_worker"
            / "db_queries"
            / "documents.py"
        )
        spec = importlib.util.spec_from_file_location(
            "_fielddesk_test_documents_queries", module_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load documents query module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.insert_chunk
    finally:
        for name, module in saved_modules.items():
            if module is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


insert_chunk = _load_insert_chunk()


def _load_embed_service():
    missing = object()
    module_names = (
        "structlog",
        "fielddesk_worker.config",
        "fielddesk_worker.db_queries",
        "fielddesk_worker.storage",
    )
    saved_modules = {name: sys.modules.get(name, missing) for name in module_names}

    class _Logger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

    structlog_mod = types.ModuleType("structlog")
    structlog_mod.get_logger = lambda: _Logger()

    config_mod = types.ModuleType("fielddesk_worker.config")
    config_mod.load_settings = lambda: None

    db_queries_mod = types.ModuleType("fielddesk_worker.db_queries")
    for name in (
        "delete_existing_chunks",
        "get_document_for_update",
        "insert_chunk",
        "insert_model_call",
        "log_model_call_isolated",
        "update_document_status",
    ):
        setattr(db_queries_mod, name, lambda *args, **kwargs: None)

    storage_mod = types.ModuleType("fielddesk_worker.storage")
    storage_mod.get_object_bytes = lambda key: b""

    sys.modules["structlog"] = structlog_mod
    sys.modules["fielddesk_worker.config"] = config_mod
    sys.modules["fielddesk_worker.db_queries"] = db_queries_mod
    sys.modules["fielddesk_worker.storage"] = storage_mod
    try:
        module_path = (
            Path(__file__).resolve().parents[1]
            / "fielddesk_worker"
            / "embeddings"
            / "service.py"
        )
        spec = importlib.util.spec_from_file_location(
            "_fielddesk_test_embedding_service", module_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load embedding service module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, module in saved_modules.items():
            if module is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class ContextualRetrievalTests(unittest.TestCase):
    def test_builds_metadata_prefix_without_mutating_chunk_text(self) -> None:
        chunk = Chunk(
            text="Replace the cartridge before repressurizing the loop.",
            chunk_index=3,
            token_count=8,
            content_hash="abc",
            heading_path=["Hydraulics", "Pressure Loss"],
            source_page=12,
            source_locator={"slide": 4},
        )

        retrieval_text = build_retrieval_text(
            document_title="Field Service SOP",
            chunk=chunk,
        )

        self.assertIn("Document: Field Service SOP", retrieval_text)
        self.assertIn("Section: Hydraulics > Pressure Loss", retrieval_text)
        self.assertIn("Page: 12", retrieval_text)
        self.assertIn("Slide: 4", retrieval_text)
        self.assertTrue(retrieval_text.endswith(chunk.text))
        self.assertEqual(chunk.text, "Replace the cartridge before repressurizing the loop.")

    def test_returns_raw_text_when_no_context_exists(self) -> None:
        chunk = Chunk(
            text="Plain standalone note.",
            chunk_index=0,
            token_count=3,
            content_hash="abc",
        )

        self.assertEqual(
            build_retrieval_text(document_title="", chunk=chunk),
            "Plain standalone note.",
        )

    def test_cleans_blank_heading_values(self) -> None:
        chunk = Chunk(
            text="Use the correct solder.",
            chunk_index=0,
            token_count=4,
            content_hash="abc",
            heading_path=[" Warranty ", "", " Workmanship\nDefects "],
        )

        retrieval_text = build_retrieval_text(
            document_title="  Warranty   Guide ",
            chunk=chunk,
        )

        self.assertIn("Document: Warranty Guide", retrieval_text)
        self.assertIn("Section: Warranty > Workmanship Defects", retrieval_text)


class InsertChunkTests(unittest.TestCase):
    def test_insert_persists_raw_text_and_retrieval_text_separately(self) -> None:
        class Cursor:
            rowcount = 1
            sql = ""
            args = ()

            def execute(self, sql, args):
                self.sql = sql
                self.args = args

        cur = Cursor()

        inserted = insert_chunk(
            cur,
            tenant_id="00000000-0000-0000-0000-000000000001",
            document_id="00000000-0000-0000-0000-000000000002",
            chunk_index=0,
            text="Raw citation text.",
            retrieval_text="Document: Warranty\n\nRaw citation text.",
            token_count=3,
            embedding=[0.1, 0.2],
            content_hash="hash",
            heading_path=["Warranty"],
            source_page=1,
            source_locator={},
        )

        self.assertTrue(inserted)
        self.assertIn("retrieval_text", cur.sql)
        self.assertEqual(cur.args[3], "Raw citation text.")
        self.assertEqual(cur.args[4], "Document: Warranty\n\nRaw citation text.")


class EmbedServiceContextualRetrievalTests(unittest.TestCase):
    def test_ingest_embeds_and_persists_contextual_retrieval_text(self) -> None:
        service = _load_embed_service()
        chunk = Chunk(
            text="Replace the cartridge before repressurizing the loop.",
            chunk_index=0,
            token_count=8,
            content_hash="hash",
            heading_path=["Hydraulics", "Pressure Loss"],
            source_page=12,
            source_locator={"slide": 4},
        )
        captured: dict[str, object] = {}

        class Provider:
            name = "test-provider"
            model = "test-model"

            def embed(self, texts):
                captured["embed_texts"] = texts
                return [[0.1, 0.2]], service.CallMetrics(
                    provider=self.name,
                    model=self.model,
                    input_tokens=123,
                    success=True,
                )

        def fake_insert_chunk(cur, **kwargs):
            captured["insert_kwargs"] = kwargs
            return True

        with (
            patch.object(
                service,
                "get_document_for_update",
                return_value={
                    "id": "doc-1",
                    "title": "Field Service SOP",
                    "object_key": "documents/doc-1.md",
                    "mime_type": "text/markdown",
                },
            ),
            patch.object(service, "update_document_status"),
            patch.object(service, "get_object_bytes", return_value=b"# ignored"),
            patch.object(service, "parse_document", return_value=[]),
            patch.object(service, "chunk_segments", return_value=[chunk]),
            patch.object(service, "_make_provider", return_value=Provider()),
            patch.object(service, "_log_embed_call"),
            patch.object(service, "delete_existing_chunks"),
            patch.object(service, "insert_chunk", side_effect=fake_insert_chunk),
        ):
            result = service.embed(
                {
                    "id": "job-1",
                    "tenant_id": "tenant-1",
                    "payload": {"document_id": "doc-1"},
                },
                object(),
            )

        embed_texts = captured["embed_texts"]
        insert_kwargs = captured["insert_kwargs"]

        self.assertEqual(result["chunks"], 1)
        self.assertEqual(insert_kwargs["text"], chunk.text)
        self.assertEqual(embed_texts, [insert_kwargs["retrieval_text"]])
        self.assertIn("Document: Field Service SOP", embed_texts[0])
        self.assertIn("Section: Hydraulics > Pressure Loss", embed_texts[0])
        self.assertIn("Page: 12", embed_texts[0])
        self.assertIn("Slide: 4", embed_texts[0])
        self.assertTrue(embed_texts[0].endswith(chunk.text))


if __name__ == "__main__":
    unittest.main()
