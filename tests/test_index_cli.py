"""Tests for the ``python -m kba index`` CLI (M2)."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

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


class IndexCliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.chunks = self.root / "chunks.jsonl"
        self.db = self.root / "chunks.db"
        self.chunks.write_text(
            "\n".join(json.dumps(make_record(i)) for i in range(3)) + "\n",
            encoding="utf-8",
        )

    def _run(self, *extra: str) -> int:
        return main(["index", "--chunks", str(self.chunks),
                     "--db", str(self.db), *extra])

    def test_success_exit_zero_and_message(self) -> None:
        from io import StringIO
        from contextlib import redirect_stdout

        out = StringIO()
        with redirect_stdout(out):
            code = self._run()
        self.assertEqual(code, 0)
        self.assertIn("indexed 3 chunk(s)", out.getvalue())
        self.assertIn(str(self.db), out.getvalue())

    def test_database_created_and_queryable(self) -> None:
        self.assertEqual(self._run(), 0)
        self.assertTrue(self.db.is_file())
        conn = sqlite3.connect(self.db)
        self.addCleanup(conn.close)
        count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        self.assertEqual(count, 3)

    def test_default_paths_from_parser(self) -> None:
        args = build_parser().parse_args(["index"])
        self.assertEqual(args.chunks, "chunks.jsonl")
        self.assertEqual(args.db, "chunks.db")

    def test_missing_chunks_file_exits_2(self) -> None:
        from io import StringIO
        from contextlib import redirect_stderr

        err = StringIO()
        with redirect_stderr(err):
            code = main(["index", "--chunks", str(self.root / "nope.jsonl"),
                         "--db", str(self.db)])
        self.assertEqual(code, 2)
        self.assertIn("not found", err.getvalue())
        self.assertFalse(self.db.exists())

    def test_malformed_chunks_exits_1(self) -> None:
        from io import StringIO
        from contextlib import redirect_stderr

        self.chunks.write_text("{not json\n", encoding="utf-8")
        err = StringIO()
        with redirect_stderr(err):
            code = self._run()
        self.assertEqual(code, 1)
        self.assertIn("cannot parse", err.getvalue())
        self.assertFalse(self.db.exists())

    def test_invalid_arguments_exit_2(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["index", "--no-such-flag"])
        self.assertEqual(ctx.exception.code, 2)

    def test_verbose_lists_per_source_counts(self) -> None:
        from io import StringIO
        from contextlib import redirect_stdout

        out = StringIO()
        with redirect_stdout(out):
            code = self._run("--verbose")
        self.assertEqual(code, 0)
        self.assertIn("docs/corpus/sample.md", out.getvalue())

    def test_repeated_runs_stay_idempotent(self) -> None:
        self.assertEqual(self._run(), 0)
        self.assertEqual(self._run(), 0)
        conn = sqlite3.connect(self.db)
        self.addCleanup(conn.close)
        count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        self.assertEqual(count, 3)

    def test_no_temp_files_left_in_output_dir(self) -> None:
        self.assertEqual(self._run(), 0)
        self.assertEqual(list(self.root.glob("*.tmp")), [])


class RealCorpusCliTestCase(unittest.TestCase):
    """Run the CLI against a temp copy of the canonical 65-chunk file."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_index_real_corpus_copy(self) -> None:
        chunks = self.root / "chunks.jsonl"
        chunks.write_bytes(REAL_CHUNKS.read_bytes())
        db = self.root / "chunks.db"
        code = main(["index", "--chunks", str(chunks), "--db", str(db)])
        self.assertEqual(code, 0)
        conn = sqlite3.connect(db)
        self.addCleanup(conn.close)
        count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        self.assertEqual(count, 65)


if __name__ == "__main__":
    unittest.main()
