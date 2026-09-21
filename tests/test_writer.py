"""Unit tests for JSONL persistence (kba.writer)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kba.chunker import Chunk
from kba.writer import chunk_to_record, write_jsonl


def make_chunk(index: int = 0, total: int = 1, text: str = "text") -> Chunk:
    return Chunk(
        id=f"docs/corpus/x.md:{index + 1}-{index + 2}",
        source_file="docs/corpus/x.md",
        format="md",
        title="Title",
        section="Section",
        chunk_index=index,
        chunk_count=total,
        start_line=index + 1,
        end_line=index + 2,
        char_count=len(text),
        text=text,
    )


class WriterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name) / "chunks.jsonl"
        self.addCleanup(self._tmp.cleanup)


class RecordTests(WriterTestCase):
    def test_record_has_all_eleven_fields_in_schema_order(self) -> None:
        record = chunk_to_record(make_chunk())
        self.assertEqual(
            list(record.keys()),
            ["id", "source_file", "format", "title", "section",
             "chunk_index", "chunk_count", "start_line", "end_line",
             "char_count", "text"],
        )
        self.assertIsInstance(record["chunk_index"], int)
        self.assertIsInstance(record["start_line"], int)
        self.assertIsInstance(record["text"], str)


class WriteTests(WriterTestCase):
    def test_roundtrip_one_json_object_per_line(self) -> None:
        records = [chunk_to_record(make_chunk(i, 3)) for i in range(3)]
        write_jsonl(records, self.out)
        lines = self.out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 3)
        parsed = [json.loads(line) for line in lines]
        self.assertEqual([p["chunk_index"] for p in parsed], [0, 1, 2])

    def test_trailing_newline_present(self) -> None:
        write_jsonl([chunk_to_record(make_chunk())], self.out)
        raw = self.out.read_bytes()
        self.assertTrue(raw.endswith(b"\n"))
        self.assertFalse(raw.endswith(b"\n\n"))

    def test_non_ascii_written_literally(self) -> None:
        write_jsonl([chunk_to_record(make_chunk(text="café → ok"))], self.out)
        raw = self.out.read_text(encoding="utf-8")
        self.assertIn("café", raw)
        self.assertIn("→", raw)
        self.assertNotIn("\\u", raw)

    def test_temp_file_removed_after_atomic_replace(self) -> None:
        write_jsonl([chunk_to_record(make_chunk())], self.out)
        tmp = self.out.with_name(self.out.name + ".tmp")
        self.assertFalse(tmp.exists())
        self.assertTrue(self.out.exists())

    def test_deterministic_byte_identical_output(self) -> None:
        records = [chunk_to_record(make_chunk(i, 5)) for i in range(5)]
        second = self.out.parent / "second.jsonl"
        write_jsonl(records, self.out)
        first_bytes = self.out.read_bytes()
        write_jsonl(records, second)
        self.assertEqual(first_bytes, second.read_bytes())

    def test_creates_missing_parent_directory(self) -> None:
        nested = self.out.parent / "deep" / "nested" / "chunks.jsonl"
        write_jsonl([chunk_to_record(make_chunk())], nested)
        self.assertTrue(nested.exists())


if __name__ == "__main__":
    unittest.main()
