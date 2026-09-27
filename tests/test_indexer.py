"""Unit tests for the derived FTS5 index layer (kba.indexer)."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kba.indexer import (
    DEFAULT_DB_PATH,
    RECORD_FIELDS,
    IndexBuildError,
    IndexBuildStats,
    InvalidChunksFile,
    build_index,
    load_records,
)

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
        "text": f"Chunk {n} discusses retries and exponential backoff schedule.",
    }
    record.update(overrides)
    return record


class LoadRecordsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _write(self, content: str | bytes, name: str = "chunks.jsonl") -> Path:
        path = self.root / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def test_loads_all_records_in_file_order(self) -> None:
        path = self._write(
            "\n".join(json.dumps(make_record(i)) for i in range(4)) + "\n"
        )
        records = load_records(path)
        self.assertEqual(len(records), 4)
        self.assertEqual([r["chunk_index"] for r in records], [0, 1, 2, 3])

    def test_blank_lines_are_skipped(self) -> None:
        path = self._write(
            json.dumps(make_record(0)) + "\n\n" + json.dumps(make_record(1)) + "\n"
        )
        self.assertEqual(len(load_records(path)), 2)

    def test_missing_file_raises_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_records(self.root / "nope.jsonl")

    def test_malformed_json_raises_invalid_chunks_file(self) -> None:
        path = self._write('{"id": "x",\nnot json\n')
        with self.assertRaises(InvalidChunksFile):
            load_records(path)

    def test_non_utf8_raises_invalid_chunks_file(self) -> None:
        path = self._write(b'{"id": "\xff\xfe"}\n')
        with self.assertRaises(InvalidChunksFile):
            load_records(path)

    def test_non_object_line_raises_invalid_chunks_file(self) -> None:
        path = self._write("[1, 2, 3]\n")
        with self.assertRaises(InvalidChunksFile):
            load_records(path)

    def test_missing_required_field_raises_invalid_chunks_file(self) -> None:
        record = make_record(0)
        del record["text"]
        path = self._write(json.dumps(record) + "\n")
        with self.assertRaises(InvalidChunksFile):
            load_records(path)

    def test_invalid_chunks_file_is_a_value_error(self) -> None:
        # The CLI maps ValueError subclasses to exit code 1.
        self.assertTrue(issubclass(InvalidChunksFile, ValueError))


class BuildIndexTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.db = self.root / "chunks.db"
        self.records = [make_record(i) for i in range(4)]

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db)

    def test_returns_plain_data_stats(self) -> None:
        stats = build_index(self.records, self.db)
        self.assertIsInstance(stats, IndexBuildStats)
        self.assertIsInstance(stats.row_count, int)
        self.assertIsInstance(stats.db_path, Path)
        self.assertEqual(stats.row_count, 4)
        self.assertEqual(stats.db_path, self.db)

    def test_schema_creates_chunks_and_fts_tables(self) -> None:
        build_index(self.records, self.db)
        with self._connect() as conn:
            names = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table')"
                )
            }
        self.assertIn("chunks", names)
        self.assertIn("chunks_fts", names)

    def test_row_count_matches_records(self) -> None:
        build_index(self.records, self.db)
        with self._connect() as conn:
            count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        self.assertEqual(count, 4)

    def test_all_eleven_fields_stored_with_values(self) -> None:
        build_index(self.records, self.db)
        with self._connect() as conn:
            columns = {r[1] for r in conn.execute("PRAGMA table_info(chunks)")}
            row = conn.execute(
                "SELECT * FROM chunks WHERE id = ?",
                (self.records[2]["id"],),
            ).fetchone()
            header = [
                r[1] for r in conn.execute("PRAGMA table_info(chunks)")
            ]
        self.assertEqual(set(RECORD_FIELDS), columns)
        stored = dict(zip(header, row))
        for field in RECORD_FIELDS:
            self.assertEqual(stored[field], self.records[2][field])

    def test_rowid_order_matches_jsonl_order(self) -> None:
        # INTERNAL invariant only: SQLite rowid is an implementation detail;
        # the public stable identity is the chunk `id`.
        build_index(self.records, self.db)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT rowid, id FROM chunks ORDER BY rowid"
            ).fetchall()
        self.assertEqual([r[1] for r in rows], [r["id"] for r in self.records])
        self.assertEqual([r[0] for r in rows], list(range(1, 5)))

    def test_public_identity_is_chunk_id(self) -> None:
        build_index(self.records, self.db)
        with self._connect() as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM chunks")]
        self.assertEqual(ids, [r["id"] for r in self.records])
        self.assertEqual(len(set(ids)), len(ids))

    def test_fts_index_matches_on_text(self) -> None:
        records = [
            make_record(0, text="alpha token"),
            make_record(1, id="doc:1", text="beta token"),
        ]
        build_index(records, self.db)
        with self._connect() as conn:
            hits = conn.execute(
                "SELECT c.id FROM chunks_fts JOIN chunks c ON c.rowid = "
                "chunks_fts.rowid WHERE chunks_fts MATCH ?",
                ("beta",),
            ).fetchall()
        self.assertEqual([h[0] for h in hits], ["doc:1"])

    def test_only_text_is_indexed_not_metadata(self) -> None:
        # `section` holds a distinctive term that never appears in `text`.
        records = [make_record(0, section="UnindexedSentinel", text="plain body")]
        build_index(records, self.db)
        with self._connect() as conn:
            hits = conn.execute(
                "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?",
                ("UnindexedSentinel",),
            ).fetchone()[0]
        self.assertEqual(hits, 0)

    def test_rebuild_is_idempotent(self) -> None:
        first = build_index(self.records, self.db)
        second = build_index(self.records, self.db)
        self.assertEqual(first.row_count, second.row_count)
        with self._connect() as conn:
            dump = conn.execute(
                "SELECT rowid, * FROM chunks ORDER BY rowid"
            ).fetchall()
        self.assertEqual(len(dump), 4)

    def test_rebuild_replaces_not_appends(self) -> None:
        build_index(self.records, self.db)
        smaller = self.records[:2]
        stats = build_index(smaller, self.db)
        self.assertEqual(stats.row_count, 2)
        with self._connect() as conn:
            count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        self.assertEqual(count, 2)

    def test_failed_build_leaves_previous_db_intact(self) -> None:
        build_index(self.records, self.db)
        before = self.db.read_bytes()
        with self.assertRaises(InvalidChunksFile):
            build_index([{"id": "only"}], self.db)  # missing fields
        self.assertEqual(self.db.read_bytes(), before)

    def test_no_temp_file_left_behind(self) -> None:
        build_index(self.records, self.db)
        leftovers = list(self.root.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_two_builds_are_logically_identical(self) -> None:
        other = self.root / "other.db"
        build_index(self.records, self.db)
        build_index(self.records, other)
        with sqlite3.connect(self.db) as a, sqlite3.connect(other) as b:
            da = a.execute("SELECT rowid, * FROM chunks ORDER BY rowid").fetchall()
            db_ = b.execute("SELECT rowid, * FROM chunks ORDER BY rowid").fetchall()
            fa = a.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'retries'"
            ).fetchall()
            fb = b.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'retries'"
            ).fetchall()
        self.assertEqual(da, db_)
        self.assertEqual(fa, fb)

    def test_missing_fts5_module_raises_index_build_error(self) -> None:
        # Simulate an environment without FTS5 by breaking the schema: the
        # module wraps sqlite3 failures so no sqlite3 error escapes.
        broken = "CREATE VIRTUAL TABLE chunks_fts USING nosuchmodule(x);"
        import kba.indexer as indexer

        original = indexer._SCHEMA_SQL
        indexer._SCHEMA_SQL = broken
        try:
            with self.assertRaises(IndexBuildError):
                build_index(self.records, self.db)
        finally:
            indexer._SCHEMA_SQL = original

    def test_default_db_path_constant(self) -> None:
        self.assertEqual(DEFAULT_DB_PATH, "chunks.db")


class RealCorpusTestCase(unittest.TestCase):
    """Index a temp copy of the canonical 65-chunk chunks.jsonl."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_indexes_the_real_canonical_file(self) -> None:
        copy = self.root / "chunks.jsonl"
        copy.write_bytes(REAL_CHUNKS.read_bytes())
        records = load_records(copy)
        self.assertEqual(len(records), 65)
        stats = build_index(records, self.root / "chunks.db")
        self.assertEqual(stats.row_count, 65)
        conn = sqlite3.connect(self.root / "chunks.db")
        self.addCleanup(conn.close)
        hits = conn.execute(
            "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'retries'"
        ).fetchone()[0]
        self.assertGreater(hits, 0)


if __name__ == "__main__":
    unittest.main()
