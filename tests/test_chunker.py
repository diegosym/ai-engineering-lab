"""Unit tests for heading-aware chunking (kba.chunker)."""
from __future__ import annotations

import unittest
from pathlib import Path

from kba.chunker import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    chunk_document,
    overlap_prefix,
)
from kba.loader import Document

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Document:
    path = FIXTURES / name
    return Document(
        path=path,
        source_file=f"tests/fixtures/{name}",
        fmt=name.rsplit(".", 1)[1],
        text=path.read_text(encoding="utf-8"),
    )


def body_of(text: str) -> str:
    """Strip the leading leaf-heading line from a chunk's text."""
    parts = text.split("\n\n", 1)
    return parts[1] if len(parts) == 2 else ""


class SectioningTests(unittest.TestCase):
    def test_title_sections_and_preamble(self) -> None:
        doc = load_fixture("long_section.md")
        chunks, warnings = chunk_document(doc)
        self.assertEqual(warnings, [])
        self.assertTrue(all(c.title == "Long Section Fixture" for c in chunks))
        sections = [c.section for c in chunks]
        self.assertIn("", sections)                      # preamble present
        self.assertIn("Endless Detail", sections)
        self.assertIn("Short Tail", sections)

    def test_no_h1_falls_back_to_stem_with_warning(self) -> None:
        chunks, warnings = chunk_document(load_fixture("no_h1.md"))
        self.assertEqual(len(warnings), 1)
        self.assertIn("no level-1 heading", warnings[0])
        self.assertEqual(chunks[0].title, "no_h1")
        self.assertEqual(chunks[0].section, "First Section")

    def test_fence_contents_not_parsed_as_headings(self) -> None:
        chunks, _ = chunk_document(load_fixture("fence_heading.md"))
        sections = {c.section for c in chunks}
        self.assertEqual(sections, {"", "Real Section"})
        fence_chunk = next(c for c in chunks if "# not a heading" in c.text)
        self.assertTrue(fence_chunk.text.startswith("## Real Section"))
        # the whole fenced block survives contiguously (never split, never
        # re-parsed as headings)
        fence_sequence = ("```text\n# not a heading\n"
                          "## also not a heading\n```")
        self.assertIn(fence_sequence, fence_chunk.text)


class SplitAndOverlapTests(unittest.TestCase):
    def test_long_section_splits_and_repeats_heading(self) -> None:
        doc = load_fixture("long_section.md")
        chunks, _ = chunk_document(doc, chunk_size=1200, overlap=150)
        long_chunks = [c for c in chunks if c.section == "Endless Detail"]
        self.assertGreater(len(long_chunks), 1)
        for chunk in long_chunks:
            self.assertTrue(chunk.text.startswith("## Endless Detail"))

    def test_overlap_is_expected_suffix_of_previous_body(self) -> None:
        doc = load_fixture("long_section.md")
        chunks, _ = chunk_document(doc, chunk_size=1200, overlap=150)
        long_chunks = [c for c in chunks if c.section == "Endless Detail"]
        self.assertGreater(len(long_chunks), 1)
        heading = "## Endless Detail\n\n"
        for prev, nxt in zip(long_chunks, long_chunks[1:]):
            self.assertTrue(prev.text.startswith(heading))
            self.assertTrue(nxt.text.startswith(heading))
            prev_body = prev.text[len(heading):]
            expected = overlap_prefix(prev_body, 150)
            self.assertTrue(prev_body.endswith(expected))
            self.assertLessEqual(len(expected), 150)
            self.assertTrue(
                nxt.text.startswith(heading + expected + "\n\n"),
                "next chunk must begin with the overlap prefix")

    def test_no_overlap_across_section_boundary(self) -> None:
        doc = load_fixture("long_section.md")
        chunks, _ = chunk_document(doc, chunk_size=1200, overlap=150)
        tail = next(c for c in chunks if c.section == "Short Tail")
        self.assertEqual(body_of(tail.text),
                         "Small closing section that must never receive "
                         "overlap from the long section.")

    def test_overlap_zero_produces_no_prefix(self) -> None:
        doc = load_fixture("long_section.md")
        chunks, _ = chunk_document(doc, chunk_size=1200, overlap=0)
        long_chunks = [c for c in chunks if c.section == "Endless Detail"]
        self.assertGreater(len(long_chunks), 1)
        for chunk in long_chunks:
            self.assertEqual(overlap_prefix(body_of(chunk.text), 0), "")
        # no overlap means no duplication and no loss across the split
        combined = "\n\n".join(body_of(c.text) for c in long_chunks)
        markers = ["The first paragraph", "The second paragraph",
                   "The third paragraph", "The fourth paragraph",
                   "The fifth paragraph", "The sixth and final paragraph"]
        for marker in markers:
            self.assertEqual(combined.count(marker), 1, marker)

    def test_overlap_prefix_helper(self) -> None:
        body = "alpha beta gamma delta epsilon"
        prefix = overlap_prefix(body, 10)
        self.assertTrue(body.endswith(prefix))
        self.assertLessEqual(len(prefix), 10)
        self.assertTrue(prefix[0].isalpha())
        self.assertEqual(overlap_prefix(body, 0), "")
        self.assertEqual(overlap_prefix(body, 999), body)


class AtomicityTests(unittest.TestCase):
    def test_oversize_table_emitted_whole(self) -> None:
        chunks, _ = chunk_document(load_fixture("big_table.md"))
        table_chunks = [c for c in chunks if "| asset-01" in c.text]
        self.assertEqual(len(table_chunks), 1)
        table_chunk = table_chunks[0]
        for row in range(1, 21):
            self.assertIn(f"| asset-{row:02d} ", table_chunk.text)
        self.assertIn("| --- | --- |", table_chunk.text)
        self.assertGreater(table_chunk.char_count, DEFAULT_CHUNK_SIZE)

    def test_paragraphs_around_table_not_absorbed(self) -> None:
        chunks, _ = chunk_document(load_fixture("big_table.md"))
        self.assertTrue(any(
            c.text.startswith("## Rows") is False and
            "Opening paragraph" in c.text for c in chunks
        ))
        self.assertTrue(any("Closing paragraph" in c.text for c in chunks))


class TextFormatTests(unittest.TestCase):
    def test_txt_single_section_no_heading_prefix(self) -> None:
        doc = load_fixture("notes.txt")
        chunks, warnings = chunk_document(doc, chunk_size=1200, overlap=150)
        self.assertEqual(warnings, [])
        self.assertTrue(all(c.format == "txt" for c in chunks))
        self.assertTrue(all(c.title == "notes" for c in chunks))
        self.assertTrue(all(c.section == "" for c in chunks))
        self.assertFalse(chunks[0].text.startswith("# "))
        self.assertTrue(chunks[0].text.startswith(
            "Plain text notes line one"))

    def test_txt_splits_with_overlap_and_keeps_hash_line_as_text(self) -> None:
        doc = load_fixture("notes.txt")
        chunks, _ = chunk_document(doc, chunk_size=400, overlap=50)
        self.assertGreater(len(chunks), 1)
        joined = "\n".join(c.text for c in chunks)
        self.assertIn("# this looks like a heading but is plain text", joined)
        self.assertTrue(all(c.section == "" for c in chunks))
        self.assertTrue(all(c.format == "txt" for c in chunks))
        # .txt chunks carry no heading line, so chunk 1's text is exactly
        # [overlap prefix] + body: it must start with the tail of chunk 0
        expected = overlap_prefix(chunks[0].text, 50)
        self.assertTrue(expected)
        self.assertTrue(chunks[1].text.startswith(expected))
        self.assertGreater(len(chunks[1].text), len(expected))


class ValidationAndInvariantTests(unittest.TestCase):
    def test_invalid_parameters_raise(self) -> None:
        doc = load_fixture("notes.txt")
        with self.assertRaises(ValueError):
            chunk_document(doc, chunk_size=100, overlap=100)
        with self.assertRaises(ValueError):
            chunk_document(doc, chunk_size=100, overlap=-1)
        with self.assertRaises(ValueError):
            chunk_document(doc, chunk_size=0, overlap=0)

    def test_invariants_hold_for_every_fixture(self) -> None:
        for name in ("long_section.md", "big_table.md", "fence_heading.md",
                     "no_h1.md", "notes.txt"):
            doc = load_fixture(name)
            chunks, _ = chunk_document(doc)
            ids = [c.id for c in chunks]
            self.assertEqual(len(ids), len(set(ids)), name)
            line_total = len(doc.text.split("\n"))
            for chunk in chunks:
                self.assertTrue(chunk.text.strip(), name)
                self.assertLessEqual(chunk.start_line, chunk.end_line, name)
                self.assertGreaterEqual(chunk.start_line, 1, name)
                self.assertLessEqual(chunk.end_line, line_total, name)
                self.assertEqual(chunk.char_count, len(chunk.text), name)
                self.assertEqual(chunk.chunk_count, len(chunks), name)
                self.assertEqual(
                    [c.chunk_index for c in chunks],
                    list(range(len(chunks))), name)
                self.assertTrue(
                    chunk.id.startswith(chunk.source_file + ":"), name)


if __name__ == "__main__":
    unittest.main()
