"""Unit tests for JSONL persistence (kba.writer)."""
from __future__ import annotations

import json
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


class TestRecord:
    def test_record_has_all_eleven_fields_in_schema_order(self) -> None:
        record = chunk_to_record(make_chunk())
        assert list(record.keys()) == [
            "id", "source_file", "format", "title", "section",
            "chunk_index", "chunk_count", "start_line", "end_line",
            "char_count", "text",
        ]
        assert isinstance(record["chunk_index"], int)
        assert isinstance(record["start_line"], int)
        assert isinstance(record["text"], str)


class TestWrite:
    def test_roundtrip_one_json_object_per_line(self, tmp_path: Path) -> None:
        out = tmp_path / "chunks.jsonl"
        records = [chunk_to_record(make_chunk(i, 3)) for i in range(3)]
        write_jsonl(records, out)
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        parsed = [json.loads(line) for line in lines]
        assert [p["chunk_index"] for p in parsed] == [0, 1, 2]

    def test_trailing_newline_present(self, tmp_path: Path) -> None:
        out = tmp_path / "chunks.jsonl"
        write_jsonl([chunk_to_record(make_chunk())], out)
        raw = out.read_bytes()
        assert raw.endswith(b"\n")
        assert not raw.endswith(b"\n\n")

    def test_non_ascii_written_literally(self, tmp_path: Path) -> None:
        out = tmp_path / "chunks.jsonl"
        write_jsonl([chunk_to_record(make_chunk(text="café → ok"))], out)
        raw = out.read_text(encoding="utf-8")
        assert "café" in raw
        assert "→" in raw
        assert "\\u" not in raw

    def test_temp_file_removed_after_atomic_replace(self, tmp_path: Path) -> None:
        out = tmp_path / "chunks.jsonl"
        write_jsonl([chunk_to_record(make_chunk())], out)
        tmp = out.with_name(out.name + ".tmp")
        assert not tmp.exists()
        assert out.exists()

    def test_deterministic_byte_identical_output(self, tmp_path: Path) -> None:
        out = tmp_path / "chunks.jsonl"
        records = [chunk_to_record(make_chunk(i, 5)) for i in range(5)]
        second = tmp_path / "second.jsonl"
        write_jsonl(records, out)
        first_bytes = out.read_bytes()
        write_jsonl(records, second)
        assert first_bytes == second.read_bytes()

    def test_creates_missing_parent_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "chunks.jsonl"
        write_jsonl([chunk_to_record(make_chunk())], nested)
        assert nested.exists()
