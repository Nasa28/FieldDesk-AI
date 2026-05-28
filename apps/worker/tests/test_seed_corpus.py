"""Dogfood the parser + chunker against the actual seed corpus.

This is the cheapest "does the whole ingest layer work on realistic content"
check we can run without a stack — no postgres, no OpenAI key, no MinIO.
If any of the 5 SOPs fails to parse or produces an empty / single-chunk
result, the rag eval against the live stack will fail in a confusing way;
better to catch it here.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fielddesk_worker.embeddings.chunker import chunk_segments
    from fielddesk_worker.evals.golden import SEED_DOCUMENT_TITLES
    from fielddesk_worker.evals.seed_corpus import CORPUS_FILES
    from fielddesk_worker.parsing import parse_document
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"worker dependencies are not installed: {exc.name}") from exc


# Repo root: tests/ → apps/worker → apps → <repo>
REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = REPO_ROOT / "infra" / "seed_corpus"


try:
    import tiktoken  # noqa: F401

    _HAS_TIKTOKEN = True
except ModuleNotFoundError:
    _HAS_TIKTOKEN = False


class SeedCorpusManifestTests(unittest.TestCase):
    def test_files_and_titles_are_one_to_one(self):
        # seed_corpus.py pairs CORPUS_FILES[i] with SEED_DOCUMENT_TITLES[i].
        # If either list grows the other must too — otherwise the upload
        # CLI silently misroutes a title.
        self.assertEqual(
            len(CORPUS_FILES),
            len(SEED_DOCUMENT_TITLES),
            "CORPUS_FILES and SEED_DOCUMENT_TITLES must stay 1:1",
        )

    def test_every_listed_file_exists_on_disk(self):
        for filename in CORPUS_FILES:
            path = CORPUS_DIR / filename
            self.assertTrue(path.is_file(), f"missing seed file: {path}")


class SeedCorpusParseTests(unittest.TestCase):
    """Each seed file must parse into at least one segment AND carry at
    least one heading_path entry — the chunker's citation story falls
    apart on heading-less content."""

    def test_each_file_parses_with_headings(self):
        for filename in CORPUS_FILES:
            with self.subTest(filename=filename):
                path = CORPUS_DIR / filename
                segments = parse_document(path.read_bytes(), "text/markdown")
                self.assertGreater(
                    len(segments), 0, f"{filename} parsed to zero segments"
                )
                # At least one segment must carry a non-empty heading path —
                # the rag retrieval shows "Document > Section > Subsection"
                # citations and these are useless without heading metadata.
                with_headings = [s for s in segments if s.heading_path]
                self.assertGreater(
                    len(with_headings),
                    0,
                    f"{filename} produced no segments with heading_path",
                )


@unittest.skipUnless(_HAS_TIKTOKEN, "tiktoken is not installed")
class SeedCorpusChunkTests(unittest.TestCase):
    """Real chunking pass — verifies tiktoken accepts the content, token
    counts come back in the expected range, and heading_path survives the
    split."""

    def test_each_file_chunks_in_token_budget(self):
        for filename in CORPUS_FILES:
            with self.subTest(filename=filename):
                path = CORPUS_DIR / filename
                segments = parse_document(path.read_bytes(), "text/markdown")
                chunks = chunk_segments(segments)
                self.assertGreater(
                    len(chunks), 0, f"{filename} produced zero chunks"
                )
                # No chunk should exceed the hard cap; the chunker re-splits
                # over-budget pieces, so a violation here means the splitter
                # gave up — that's a bug, not a content issue.
                for chunk in chunks:
                    self.assertLessEqual(
                        chunk.token_count,
                        1024,
                        f"{filename} chunk {chunk.chunk_index} over MAX_TOKENS_PER_CHUNK",
                    )

    def test_chunks_carry_heading_path_for_citations(self):
        for filename in CORPUS_FILES:
            with self.subTest(filename=filename):
                path = CORPUS_DIR / filename
                segments = parse_document(path.read_bytes(), "text/markdown")
                chunks = chunk_segments(segments)
                with_headings = [c for c in chunks if c.heading_path]
                self.assertGreater(
                    len(with_headings),
                    0,
                    f"{filename} produced no chunks with heading_path; "
                    "citations will be unusable",
                )

    def test_content_hashes_are_unique_within_a_document(self):
        # The partial UNIQUE on (document_id, content_hash) is the
        # idempotency mechanism. If two chunks in the same document
        # produce the same hash, the second insert silently drops, and
        # the operator loses content. Heading-path is included in the
        # hash to prevent same-text different-section collisions.
        for filename in CORPUS_FILES:
            with self.subTest(filename=filename):
                path = CORPUS_DIR / filename
                segments = parse_document(path.read_bytes(), "text/markdown")
                chunks = chunk_segments(segments)
                hashes = [c.content_hash for c in chunks]
                self.assertEqual(
                    len(hashes),
                    len(set(hashes)),
                    f"{filename} produced duplicate content_hashes",
                )


if __name__ == "__main__":
    unittest.main()
