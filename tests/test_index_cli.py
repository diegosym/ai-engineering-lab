"""Tests for the ``python -m kba index`` CLI (M2)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from kba.__main__ import build_parser, main

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_CHUNKS = REPO_ROOT / "chunks.jsonl"


def make_record(n: int, **overrides) -> dict:
    record = {
        "id": f"docs/corpus/sample.md:1-{n}",
        "source_file": "docs/corpus/sample.md",
        "format": "md",
        "title": "Sample Document",
        "section": f"Section {n}",
        "chunk_index": n,
        "chunk_count": 3,
        "start_line": n,
        "end_line": n + 10,
        "char_count": 100 + n,
        "text": f"Chunk {n} discusses retries and backoff.",
    }
    record.update(overrides)
    return record


class TestIndexCli:
    @pytest.fixture(autouse=True)
    def _env(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.chunks = tmp_path / "chunks.jsonl"
        self.db = tmp_path / "chunks.db"
        self.chunks.write_text(
            "\n".join(json.dumps(make_record(i)) for i in range(3)) + "\n",
            encoding="utf-8",
        )

    def _run(self, *extra: str) -> int:
        return main(["index", "--chunks", str(self.chunks),
                     "--db", str(self.db), *extra])

    def test_success_exit_zero_and_message(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = self._run()
        assert code == 0
        assert "indexed 3 chunk(s)" in out.getvalue()
        assert str(self.db) in out.getvalue()

    def test_database_created_and_queryable(self) -> None:
        assert self._run() == 0
        assert self.db.is_file()
        with sqlite3.connect(self.db) as conn:
            count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        assert count == 3

    def test_default_paths_from_parser(self) -> None:
        args = build_parser().parse_args(["index"])
        assert args.chunks == "chunks.jsonl"
        assert args.db == "chunks.db"

    def test_missing_chunks_file_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["index", "--chunks", str(self.root / "nope.jsonl"),
                         "--db", str(self.db)])
        assert code == 2
        assert "not found" in err.getvalue()
        assert not self.db.exists()

    def test_malformed_chunks_exits_1(self) -> None:
        self.chunks.write_text("{not json\n", encoding="utf-8")
        err = StringIO()
        with redirect_stderr(err):
            code = self._run()
        assert code == 1
        assert "cannot parse" in err.getvalue()
        assert not self.db.exists()

    def test_invalid_arguments_exit_2(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["index", "--no-such-flag"])
        assert exc_info.value.code == 2

    def test_verbose_lists_per_source_counts(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = self._run("--verbose")
        assert code == 0
        assert "docs/corpus/sample.md" in out.getvalue()

    def test_repeated_runs_stay_idempotent(self) -> None:
        assert self._run() == 0
        assert self._run() == 0
        with sqlite3.connect(self.db) as conn:
            count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        assert count == 3

    def test_no_temp_files_left_in_output_dir(self) -> None:
        assert self._run() == 0
        assert list(self.root.glob("*.tmp")) == []


class TestRealCorpusCli:
    """Run the CLI against a temp copy of the canonical 65-chunk file."""

    def test_index_real_corpus_copy(self, tmp_path: Path) -> None:
        chunks = tmp_path / "chunks.jsonl"
        chunks.write_bytes(REAL_CHUNKS.read_bytes())
        db = tmp_path / "chunks.db"
        code = main(["index", "--chunks", str(chunks), "--db", str(db)])
        assert code == 0
        with sqlite3.connect(db) as conn:
            count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        assert count == 65
