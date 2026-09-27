"""Unit tests for heading-aware chunking (kba.chunker)."""
from __future__ import annotations

from pathlib import Path

import pytest

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


class TestSectioning:
    def test_title_sections_and_preamble(self) -> None:
        doc = load_fixture("long_section.md")
        chunks, warnings = chunk_document(doc)
        assert warnings == []
        assert all(c.title == "Long Section Fixture" for c in chunks)
        sections = [c.section for c in chunks]
        assert "" in sections                       # preamble present
        assert "Endless Detail" in sections
        assert "Short Tail" in sections

    def test_no_h1_falls_back_to_stem_with_warning(self) -> None:
        chunks, warnings = chunk_document(load_fixture("no_h1.md"))
        assert len(warnings) == 1
        assert "no level-1 heading" in warnings[0]
        assert chunks[0].title == "no_h1"
        assert chunks[0].section == "First Section"

    def test_fence_contents_not_parsed_as_headings(self) -> None:
        chunks, _ = chunk_document(load_fixture("fence_heading.md"))
        sections = {c.section for c in chunks}
        assert sections == {"", "Real Section"}
        fence_chunk = next(c for c in chunks if "# not a heading" in c.text)
        assert fence_chunk.text.startswith("## Real Section")
        # the whole fenced block survives contiguously (never split, never
        # re-parsed as headings)
        fence_sequence = ("```text\n# not a heading\n"
                          "## also not a heading\n```")
        assert fence_sequence in fence_chunk.text


class TestSplitAndOverlap:
    def test_long_section_splits_and_repeats_heading(self) -> None:
        doc = load_fixture("long_section.md")
        chunks, _ = chunk_document(doc, chunk_size=1200, overlap=150)
        long_chunks = [c for c in chunks if c.section == "Endless Detail"]
        assert len(long_chunks) > 1
        for chunk in long_chunks:
            assert chunk.text.startswith("## Endless Detail")

    def test_overlap_is_expected_suffix_of_previous_body(self) -> None:
        doc = load_fixture("long_section.md")
        chunks, _ = chunk_document(doc, chunk_size=1200, overlap=150)
        long_chunks = [c for c in chunks if c.section == "Endless Detail"]
        assert len(long_chunks) > 1
        heading = "## Endless Detail\n\n"
        for prev, nxt in zip(long_chunks, long_chunks[1:]):
            assert prev.text.startswith(heading)
            assert nxt.text.startswith(heading)
            prev_body = prev.text[len(heading):]
            expected = overlap_prefix(prev_body, 150)
            assert prev_body.endswith(expected)
            assert len(expected) <= 150
            assert nxt.text.startswith(heading + expected + "\n\n"), (
                "next chunk must begin with the overlap prefix")

    def test_no_overlap_across_section_boundary(self) -> None:
        doc = load_fixture("long_section.md")
        chunks, _ = chunk_document(doc, chunk_size=1200, overlap=150)
        tail = next(c for c in chunks if c.section == "Short Tail")
        assert body_of(tail.text) == (
            "Small closing section that must never receive "
            "overlap from the long section.")

    def test_overlap_zero_produces_no_prefix(self) -> None:
        doc = load_fixture("long_section.md")
        chunks, _ = chunk_document(doc, chunk_size=1200, overlap=0)
        long_chunks = [c for c in chunks if c.section == "Endless Detail"]
        assert len(long_chunks) > 1
        for chunk in long_chunks:
            assert overlap_prefix(body_of(chunk.text), 0) == ""
        # no overlap means no duplication and no loss across the split
        combined = "\n\n".join(body_of(c.text) for c in long_chunks)
        markers = ["The first paragraph", "The second paragraph",
                   "The third paragraph", "The fourth paragraph",
                   "The fifth paragraph", "The sixth and final paragraph"]
        for marker in markers:
            assert combined.count(marker) == 1, marker

    def test_overlap_prefix_helper(self) -> None:
        body = "alpha beta gamma delta epsilon"
        prefix = overlap_prefix(body, 10)
        assert body.endswith(prefix)
        assert len(prefix) <= 10
        assert prefix[0].isalpha()
        assert overlap_prefix(body, 0) == ""
        assert overlap_prefix(body, 999) == body


class TestAtomicity:
    def test_oversize_table_emitted_whole(self) -> None:
        chunks, _ = chunk_document(load_fixture("big_table.md"))
        table_chunks = [c for c in chunks if "| asset-01" in c.text]
        assert len(table_chunks) == 1
        table_chunk = table_chunks[0]
        for row in range(1, 21):
            assert f"| asset-{row:02d} " in table_chunk.text
        assert "| --- | --- |" in table_chunk.text
        assert table_chunk.char_count > DEFAULT_CHUNK_SIZE

    def test_paragraphs_around_table_not_absorbed(self) -> None:
        chunks, _ = chunk_document(load_fixture("big_table.md"))
        assert any(
            c.text.startswith("## Rows") is False and
            "Opening paragraph" in c.text for c in chunks
        )
        assert any("Closing paragraph" in c.text for c in chunks)


class TestTextFormat:
    def test_txt_single_section_no_heading_prefix(self) -> None:
        doc = load_fixture("notes.txt")
        chunks, warnings = chunk_document(doc, chunk_size=1200, overlap=150)
        assert warnings == []
        assert all(c.format == "txt" for c in chunks)
        assert all(c.title == "notes" for c in chunks)
        assert all(c.section == "" for c in chunks)
        assert not chunks[0].text.startswith("# ")
        assert chunks[0].text.startswith("Plain text notes line one")

    def test_txt_splits_with_overlap_and_keeps_hash_line_as_text(self) -> None:
        doc = load_fixture("notes.txt")
        chunks, _ = chunk_document(doc, chunk_size=400, overlap=50)
        assert len(chunks) > 1
        joined = "\n".join(c.text for c in chunks)
        assert "# this looks like a heading but is plain text" in joined
        assert all(c.section == "" for c in chunks)
        assert all(c.format == "txt" for c in chunks)
        # .txt chunks carry no heading line, so chunk 1's text is exactly
        # [overlap prefix] + body: it must start with the tail of chunk 0
        expected = overlap_prefix(chunks[0].text, 50)
        assert expected
        assert chunks[1].text.startswith(expected)
        assert len(chunks[1].text) > len(expected)


class TestValidationAndInvariants:
    def test_invalid_parameters_raise(self) -> None:
        doc = load_fixture("notes.txt")
        with pytest.raises(ValueError):
            chunk_document(doc, chunk_size=100, overlap=100)
        with pytest.raises(ValueError):
            chunk_document(doc, chunk_size=100, overlap=-1)
        with pytest.raises(ValueError):
            chunk_document(doc, chunk_size=0, overlap=0)

    def test_invariants_hold_for_every_fixture(self) -> None:
        for name in ("long_section.md", "big_table.md", "fence_heading.md",
                     "no_h1.md", "notes.txt"):
            doc = load_fixture(name)
            chunks, _ = chunk_document(doc)
            ids = [c.id for c in chunks]
            assert len(ids) == len(set(ids)), name
            line_total = len(doc.text.split("\n"))
            for chunk in chunks:
                assert chunk.text.strip(), name
                assert chunk.start_line <= chunk.end_line, name
                assert chunk.start_line >= 1, name
                assert chunk.end_line <= line_total, name
                assert chunk.char_count == len(chunk.text), name
                assert chunk.chunk_count == len(chunks), name
                assert ([c.chunk_index for c in chunks]
                        == list(range(len(chunks)))), name
                assert chunk.id.startswith(chunk.source_file + ":"), name
