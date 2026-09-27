"""Shared pytest fixtures — narrowly scoped by explicit approval (M3-PRE).

Only the duplication identified during the unittest→pytest migration lives
here; test-specific setup stays in its test module:

- ``make_record``    — synthetic chunks.jsonl record factory (identical
                       11-field structure was copy-pasted in 4 test modules).
- ``real_index_db``  — fresh FTS5 database built from the canonical
                       chunks.jsonl into a temp dir (the same copy+build
                       setup was repeated in 3 test modules).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kba.indexer import build_index, load_records

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_CHUNKS = REPO_ROOT / "chunks.jsonl"


@pytest.fixture
def make_record():
    """Factory for synthetic chunk records following the 11-field schema."""
    def _make(n: int, **overrides) -> dict:
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
            "text": f"Chunk {n} discusses retries and "
                    "exponential backoff schedule.",
        }
        record.update(overrides)
        return record

    return _make


@pytest.fixture
def real_index_db(tmp_path: Path) -> Path:
    """Path to an FTS5 db built from a temp copy of canonical chunks.jsonl."""
    copy = tmp_path / "chunks.jsonl"
    copy.write_bytes(REAL_CHUNKS.read_bytes())
    db = tmp_path / "chunks.db"
    build_index(load_records(copy), db)
    return db
