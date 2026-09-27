"""Derived FTS5 index layer (M2) — builds the SQLite database from ``chunks.jsonl``.

``chunks.jsonl`` stays the canonical artifact; the ``.db`` file produced here is a
derived, rebuildable artifact (full rebuild on every run, atomically replaced).

Architecture boundary:
    This module is the ONLY place SQL/SQLite specifics may appear today (the
    future retrieval module will be the second). No ``sqlite3`` objects escape
    this module — callers receive plain data (:class:`IndexBuildStats`).

Identity contract:
    The chunk ``id`` (from ``chunks.jsonl``) is the **public stable identity**
    of a chunk. SQLite ``rowid`` is an **internal implementation detail** of
    this module: tests may assert current row ordering as an internal
    invariant, but no application code outside this module may rely on it.

Schema:
    ``chunks``      — all eleven chunk fields (canonical searchable content +
                      metadata, stored once).
    ``chunks_fts``  — external-content FTS5 index over ``text`` only; title,
                      section, source_file and other metadata are stored but
                      NOT indexed (choosing searchable fields is a query-policy
                      decision deferred to the search step).
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "chunks.db"

#: The eleven fields of a chunks.jsonl record, in schema order.
RECORD_FIELDS: tuple[str, ...] = (
    "id",
    "source_file",
    "format",
    "title",
    "section",
    "chunk_index",
    "chunk_count",
    "start_line",
    "end_line",
    "char_count",
    "text",
)

_SCHEMA_SQL = """
CREATE TABLE chunks (
    id          TEXT PRIMARY KEY,
    source_file TEXT NOT NULL,
    format      TEXT NOT NULL,
    title       TEXT NOT NULL,
    section     TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    char_count  INTEGER NOT NULL,
    text        TEXT NOT NULL
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text,
    content='chunks',
    content_rowid='rowid'
);
"""

_INSERT_SQL = (
    "INSERT INTO chunks ("
    + ", ".join(RECORD_FIELDS)
    + ") VALUES ("
    + ", ".join("?" for _ in RECORD_FIELDS)
    + ")"
)

#: After ``chunks`` is populated, rebuild the external-content FTS index from it.
_FTS_REBUILD_SQL = "INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')"


class InvalidChunksFile(ValueError):
    """chunks.jsonl exists but cannot be parsed as valid chunk records."""


class IndexBuildError(Exception):
    """The FTS5 database could not be built (SQLite/FTS5 failure)."""


@dataclass(frozen=True)
class IndexBuildStats:
    """Plain-data result of a build — no sqlite3 objects cross the boundary."""

    row_count: int
    db_path: Path


def load_records(chunks_path: Path) -> list[dict[str, Any]]:
    """Read and validate all records from *chunks_path* (canonical source).

    Raises:
        FileNotFoundError: the file does not exist.
        InvalidChunksFile: not valid UTF-8, not valid JSON, or a record that is
            not an object carrying the required fields.
    """
    try:
        raw = chunks_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except UnicodeDecodeError as exc:
        raise InvalidChunksFile(f"not valid UTF-8: {exc}") from exc

    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InvalidChunksFile(f"line {lineno}: invalid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise InvalidChunksFile(f"line {lineno}: expected a JSON object")
        missing = [f for f in RECORD_FIELDS if f not in record]
        if missing:
            raise InvalidChunksFile(
                f"line {lineno}: missing field(s): {', '.join(missing)}"
            )
        records.append(record)
    return records


def _validate_records(records: Sequence[dict[str, Any]]) -> None:
    """Fail fast (before touching the database) on malformed records."""
    for i, record in enumerate(records):
        if not isinstance(record, dict):
            raise InvalidChunksFile(f"record {i}: expected a dict")
        missing = [f for f in RECORD_FIELDS if f not in record]
        if missing:
            raise InvalidChunksFile(
                f"record {i}: missing field(s): {', '.join(missing)}"
            )


def build_index(
    records: Sequence[dict[str, Any]], db_path: Path
) -> IndexBuildStats:
    """(Re)build the FTS5 database at *db_path* from *records*.

    Full-rebuild semantics: the database is created fresh in a temporary
    sibling file and atomically renamed over *db_path*, so a failed build
    never leaves a partial database and never corrupts a previous one.
    Determinism: records are inserted in the order given (``chunks.jsonl``
    order), so rowids and query results are reproducible for identical input.
    """
    _validate_records(records)

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_name(db_path.name + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    try:
        conn = sqlite3.connect(tmp_path)
    except sqlite3.Error as exc:  # pragma: no cover — extremely rare
        raise IndexBuildError(str(exc)) from exc

    try:
        with conn:
            conn.executescript(_SCHEMA_SQL)
            conn.executemany(
                _INSERT_SQL, [tuple(r[f] for f in RECORD_FIELDS) for r in records]
            )
            conn.execute(_FTS_REBUILD_SQL)
        actual = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    except sqlite3.Error as exc:
        conn.close()
        tmp_path.unlink(missing_ok=True)
        raise IndexBuildError(str(exc)) from exc
    finally:
        conn.close()

    if actual != len(records):  # pragma: no cover — defensive
        tmp_path.unlink(missing_ok=True)
        raise IndexBuildError(
            f"indexed {actual} row(s) but expected {len(records)}"
        )

    try:
        tmp_path.replace(db_path)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise IndexBuildError(str(exc)) from exc

    return IndexBuildStats(row_count=actual, db_path=db_path)
