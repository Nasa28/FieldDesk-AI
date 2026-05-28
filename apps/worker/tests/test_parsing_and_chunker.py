from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fielddesk_worker.embeddings.chunker import chunk_segments
    from fielddesk_worker.parsing import (
        SUPPORTED_MIME_TYPES,
        ParsedSegment,
        parse_document,
    )
    from fielddesk_worker.parsing.markdown import parse_markdown
    from fielddesk_worker.parsing.text import parse_text
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"worker dependencies are not installed: {exc.name}") from exc


class TextParserTests(unittest.TestCase):
    def test_strips_whitespace_and_returns_one_segment(self):
        segments = parse_text(b"   hello world   \n\n")
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "hello world")
        self.assertEqual(segments[0].heading_path, [])

    def test_empty_returns_no_segments(self):
        self.assertEqual(parse_text(b""), [])
        self.assertEqual(parse_text(b"\n   \n"), [])

    def test_falls_back_to_latin1_on_bad_utf8(self):
        # 0xa1 is invalid utf-8 but valid latin-1 (¡).
        segments = parse_text(b"\xa1hola")
        self.assertEqual(len(segments), 1)


class MarkdownParserTests(unittest.TestCase):
    def test_one_heading_one_section(self):
        md = b"# Title\n\nBody text here.\n"
        segments = parse_markdown(md)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].heading_path, ["Title"])
        self.assertIn("Body text", segments[0].text)

    def test_nested_headings_carry_path(self):
        md = (
            b"# Hydraulic Pumps\n"
            b"intro paragraph\n"
            b"## Troubleshooting\n"
            b"### Pressure Loss\n"
            b"Step 1: check the inlet.\n"
        )
        segments = parse_markdown(md)
        # 3 sections: under "Hydraulic Pumps", under "+Troubleshooting"
        # (empty body so no segment), under "+Pressure Loss". The empty
        # heading should not emit an empty-body segment.
        self.assertGreaterEqual(len(segments), 2)
        last = segments[-1]
        self.assertEqual(last.heading_path, ["Hydraulic Pumps", "Troubleshooting", "Pressure Loss"])

    def test_headings_inside_fenced_blocks_are_ignored(self):
        md = (
            b"# Real Heading\n"
            b"```\n"
            b"# This looks like a heading but isn't\n"
            b"```\n"
            b"after fence\n"
        )
        segments = parse_markdown(md)
        # All text belongs under "Real Heading"; the fence inside should
        # NOT have created a second section.
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].heading_path, ["Real Heading"])

    def test_dedented_heading_truncates_stack(self):
        # Going from H3 back up to H2 should pop the H3 off the stack.
        md = (
            b"## Section A\n"
            b"### Sub A.1\n"
            b"first body\n"
            b"## Section B\n"
            b"second body\n"
        )
        segments = parse_markdown(md)
        paths = [s.heading_path for s in segments]
        self.assertIn(["Section A", "Sub A.1"], paths)
        self.assertIn(["Section B"], paths)


class ChunkerTests(unittest.TestCase):
    def test_short_segment_passes_through_unchanged(self):
        segments = [
            ParsedSegment(text="quick brown fox", heading_path=["A"], source_page=1)
        ]
        chunks = chunk_segments(segments)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "quick brown fox")
        self.assertEqual(chunks[0].heading_path, ["A"])
        self.assertEqual(chunks[0].source_page, 1)
        # chunk_index is monotonically increasing from 0.
        self.assertEqual(chunks[0].chunk_index, 0)

    def test_long_segment_splits_with_overlap(self):
        # Build a body well above 512 tokens by repeating a sentence.
        sentence = "This is a test sentence for the chunker. " * 200
        segments = [ParsedSegment(text=sentence, heading_path=["Big"])]
        chunks = chunk_segments(segments, target_tokens=512, overlap_tokens=64)
        self.assertGreater(len(chunks), 1)
        # Each chunk should respect the token budget (allow some slack for
        # the recursive splitter not landing exactly on boundary).
        for c in chunks:
            self.assertLessEqual(c.token_count, 600)
            self.assertEqual(c.heading_path, ["Big"])
        # Indexes are sequential.
        self.assertEqual([c.chunk_index for c in chunks], list(range(len(chunks))))

    def test_content_hash_is_stable_for_same_input(self):
        s = ParsedSegment(text="hello world", heading_path=["A"], source_page=2)
        c1 = chunk_segments([s])
        c2 = chunk_segments([s])
        self.assertEqual(c1[0].content_hash, c2[0].content_hash)

    def test_content_hash_differs_when_page_differs(self):
        # Same text on two different pages must produce distinct hashes,
        # otherwise the idempotent UPSERT would silently drop a chunk.
        a = ParsedSegment(text="boilerplate", source_page=1)
        b = ParsedSegment(text="boilerplate", source_page=2)
        ca = chunk_segments([a])[0]
        cb = chunk_segments([b])[0]
        self.assertNotEqual(ca.content_hash, cb.content_hash)

    def test_empty_segments_produce_zero_chunks(self):
        self.assertEqual(chunk_segments([]), [])
        self.assertEqual(chunk_segments([ParsedSegment(text="")]), [])

    def test_rejects_bad_params(self):
        with self.assertRaises(ValueError):
            chunk_segments([ParsedSegment(text="x")], target_tokens=0)
        with self.assertRaises(ValueError):
            chunk_segments([ParsedSegment(text="x")], target_tokens=10, overlap_tokens=10)


class ParseDocumentRouterTests(unittest.TestCase):
    def test_supported_mime_types_match_what_router_knows(self):
        # If this set changes, the Go handler's allowedDocumentMimes needs
        # the same update — the test exists to remind us.
        self.assertEqual(
            set(SUPPORTED_MIME_TYPES.keys()),
            {
                "text/plain",
                "text/markdown",
                "text/x-markdown",
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            },
        )

    def test_unsupported_mime_raises(self):
        from fielddesk_worker.parsing import ParseError

        with self.assertRaises(ParseError):
            parse_document(b"<x/>", "application/xml")

    def test_routes_text_correctly(self):
        segments = parse_document(b"hello", "text/plain")
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "hello")


if __name__ == "__main__":
    unittest.main()
