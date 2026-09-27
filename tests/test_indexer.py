"""Unit tests for the derived FTS5 index layer (kba.indexer)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import kba.indexer as indexer
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


def write_chunks(root: Path, content: str | bytes,
                 name: str = "chunks.jsonl") -> Path:
    path = root / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


class TestLoadRecords:
    @pytest.fixture(autouse=True)
    def _root(self, tmp_path: Path) -> None:
        self.root = tmp_path

    def test_loads_all_records_in_file_order(self, make_record) -> None:
        path = write_chunks(
            self.root,
            "\n".join(json.dumps(make_record(i)) for i in range(4)) + "\n",
        )
        records = load_records(path)
        assert len(records) == 4
        assert [r["chunk_index"] for r in records] == [0, 1, 2, 3]

    def test_blank_lines_are_skipped(self, make_record) -> None:
        path = write_chunks(
            self.root,
            json.dumps(make_record(0)) + "\n\n"
            + json.dumps(make_record(1)) + "\n",
        )
        assert len(load_records(path)) == 2

    def test_missing_file_raises_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_records(self.root / "nope.jsonl")

    def test_malformed_json_raises_invalid_chunks_file(self) -> None:
        path = write_chunks(self.root, '{"id": "x",\nnot json\n')
        with pytest.raises(InvalidChunksFile):
            load_records(path)

    def test_non_utf8_raises_invalid_chunks_file(self) -> None:
        path = write_chunks(self.root, b'{"id": "\xff\xfe"}\n')
        with pytest.raises(InvalidChunksFile):
            load_records(path)

    def test_non_object_line_raises_invalid_chunks_file(self) -> None:
        path = write_chunks(self.root, "[1, 2, 3]\n")
        with pytest.raises(InvalidChunksFile):
            load_records(path)

    def test_missing_required_field_raises_invalid_chunks_file(
            self, make_record) -> None:
        record = make_record(0)
        del record["text"]
        path = write_chunks(self.root, json.dumps(record) + "\n")
        with pytest.raises(InvalidChunksFile):
            load_records(path)

    def test_invalid_chunks_file_is_a_value_error(self) -> None:
        # The CLI maps ValueError subclasses to exit code 1.
        assert issubclass(InvalidChunksFile, ValueError)


class TestBuildIndex:
    @pytest.fixture(autouse=True)
    def _env(self, tmp_path: Path, make_record) -> SimpleNamespace:
        env = SimpleNamespace(
            root=tmp_path,
            db=tmp_path / "chunks.db",
            records=[make_record(i) for i in range(4)],
        )
        self.root, self.db, self.records = env.root, env.db, env.records
        return env

    def test_returns_plain_data_stats(self) -> None:
        stats = build_index(self.records, self.db)
        assert isinstance(stats, IndexBuildStats)
        assert isinstance(stats.row_count, int)
        assert isinstance(stats.db_path, Path)
        assert stats.row_count == 4
        assert stats.db_path == self.db

    def test_schema_creates_chunks_and_fts_tables(self) -> None:
        build_index(self.records, self.db)
        with sqlite3.connect(self.db) as conn:
            names = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table')"
                )
            }
        assert "chunks" in names
        assert "chunks_fts" in names

    def test_row_count_matches_records(self) -> None:
        build_index(self.records, self.db)
        with sqlite3.connect(self.db) as conn:
            count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        assert count == 4

    def test_all_eleven_fields_stored_with_values(self) -> None:
        build_index(self.records, self.db)
        with sqlite3.connect(self.db) as conn:
            columns = {r[1] for r in conn.execute("PRAGMA table_info(chunks)")}
            row = conn.execute(
                "SELECT * FROM chunks WHERE id = ?",
                (self.records[2]["id"],),
            ).fetchone()
            header = [
                r[1] for r in conn.execute("PRAGMA table_info(chunks)")
            ]
        assert set(RECORD_FIELDS) == columns
        stored = dict(zip(header, row))
        for field in RECORD_FIELDS:
            assert stored[field] == self.records[2][field]

    def test_rowid_order_matches_jsonl_order(self) -> None:
        # INTERNAL invariant only: SQLite rowid is an implementation detail;
        # the public stable identity is the chunk `id`.
        build_index(self.records, self.db)
        with sqlite3.connect(self.db) as conn:
            rows = conn.execute(
                "SELECT rowid, id FROM chunks ORDER BY rowid"
            ).fetchall()
        assert [r[1] for r in rows] == [r["id"] for r in self.records]
        assert [r[0] for r in rows] == [1, 2, 3, 4]

    def test_public_identity_is_chunk_id(self) -> None:
        build_index(self.records, self.db)
        with sqlite3.connect(self.db) as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM chunks")]
        assert ids == [r["id"] for r in self.records]
        assert len(set(ids)) == len(ids)

    def test_fts_index_matches_on_text(self, make_record) -> None:
        records = [
            make_record(0, text="alpha token"),
            make_record(1, id="doc:1", text="beta token"),
        ]
        build_index(records, self.db)
        with sqlite3.connect(self.db) as conn:
            hits = conn.execute(
                "SELECT c.id FROM chunks_fts JOIN chunks c ON c.rowid = "
                "chunks_fts.rowid WHERE chunks_fts MATCH ?",
                ("beta",),
            ).fetchall()
        assert [h[0] for h in hits] == ["doc:1"]

    def test_only_text_is_indexed_not_metadata(self, make_record) -> None:
        # `section` holds a distinctive term that never appears in `text`.
        records = [make_record(0, section="UnindexedSentinel",
                               text="plain body")]
        build_index(records, self.db)
        with sqlite3.connect(self.db) as conn:
            hits = conn.execute(
                "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?",
                ("UnindexedSentinel",),
            ).fetchone()[0]
        assert hits == 0

    def test_rebuild_is_idempotent(self) -> None:
        first = build_index(self.records, self.db)
        second = build_index(self.records, self.db)
        assert first.row_count == second.row_count
        with sqlite3.connect(self.db) as conn:
            dump = conn.execute(
                "SELECT rowid, * FROM chunks ORDER BY rowid"
            ).fetchall()
        assert len(dump) == 4

    def test_rebuild_replaces_not_appends(self) -> None:
        build_index(self.records, self.db)
        smaller = self.records[:2]
        stats = build_index(smaller, self.db)
        assert stats.row_count == 2
        with sqlite3.connect(self.db) as conn:
            count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        assert count == 2

    def test_failed_build_leaves_previous_db_intact(self) -> None:
        build_index(self.records, self.db)
        before = self.db.read_bytes()
        with pytest.raises(InvalidChunksFile):
            build_index([{"id": "only"}], self.db)  # missing fields
        assert self.db.read_bytes() == before

    def test_no_temp_file_left_behind(self) -> None:
        build_index(self.records, self.db)
        leftovers = list(self.root.glob("*.tmp"))
        assert leftovers == []

    def test_two_builds_are_logically_identical(self) -> None:
        other = self.root / "other.db"
        build_index(self.records, self.db)
        build_index(self.records, other)
        with sqlite3.connect(self.db) as a, sqlite3.connect(other) as b:
            da = a.execute(
                "SELECT rowid, * FROM chunks ORDER BY rowid").fetchall()
            db_ = b.execute(
                "SELECT rowid, * FROM chunks ORDER BY rowid").fetchall()
            fa = a.execute(
                "SELECT rowid FROM chunks_fts "
                "WHERE chunks_fts MATCH 'retries'"
            ).fetchall()
            fb = b.execute(
                "SELECT rowid FROM chunks_fts "
                "WHERE chunks_fts MATCH 'retries'"
            ).fetchall()
        assert da == db_
        assert fa == fb

    def test_missing_fts5_module_raises_index_build_error(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Simulate an environment without FTS5 by breaking the schema: the
        # module wraps sqlite3 failures so no sqlite3 error escapes.
        # monkeypatch restores _SCHEMA_SQL even if the test fails.
        broken = "CREATE VIRTUAL TABLE chunks_fts USING nosuchmodule(x);"
        monkeypatch.setattr(indexer, "_SCHEMA_SQL", broken)
        with pytest.raises(IndexBuildError):
            build_index(self.records, self.db)

    def test_default_db_path_constant(self) -> None:
        assert DEFAULT_DB_PATH == "chunks.db"


class TestRealCorpus:
    """Index a temp copy of the canonical 65-chunk chunks.jsonl."""

    def test_indexes_the_real_canonical_file(self, tmp_path: Path) -> None:
        copy = tmp_path / "chunks.jsonl"
        copy.write_bytes(REAL_CHUNKS.read_bytes())
        records = load_records(copy)
        assert len(records) == 65
        stats = build_index(records, tmp_path / "chunks.db")
        assert stats.row_count == 65
        with sqlite3.connect(tmp_path / "chunks.db") as conn:
            hits = conn.execute(
                "SELECT count(*) FROM chunks_fts "
                "WHERE chunks_fts MATCH 'retries'"
            ).fetchone()[0]
        assert hits > 0
