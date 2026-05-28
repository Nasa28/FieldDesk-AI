from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
