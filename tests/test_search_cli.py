"""Tests for the ``python -m kba search`` CLI adapter (M2)."""
from __future__ import annotations

import contextlib
import io
import json
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
        "text": f"Chunk {n} discusses retries and exponential backoff.",
    }
    record.update(overrides)
    return record


class TestSearchCli:
    @pytest.fixture(autouse=True)
    def _env(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.chunks = tmp_path / "chunks.jsonl"
        self.db = tmp_path / "chunks.db"
        # One short record and one long record (exceeds the 400-char preview).
        self.long_text = (
            "retry backoff jitter detail line with more context. " * 15
        ).strip()
        self.chunks.write_text(
            "\n".join([
                json.dumps(make_record(0)),
                json.dumps(make_record(1, id="doc:long", section="",
                                     text=self.long_text)),
                json.dumps(make_record(2, id="doc:backoff",
                                       text="chunk about backoff only")),
            ]) + "\n",
            encoding="utf-8",
        )
        from kba.indexer import build_index, load_records

        build_index(load_records(self.chunks), self.db)

    def _run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["search", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_success_shows_results_with_score_source_section_text(self) -> None:
        code, out, err = self._run("retries", "--db", str(self.db))
        assert code == 0
        assert "result(s) for: retries" in out
        assert "docs/corpus/sample.md" in out
        assert "Section 0" in out
        assert "id: docs/corpus/sample.md:1-0" in out
        assert "discusses retries" in out
        assert err == ""

    def test_default_k_is_five(self) -> None:
        args = build_parser().parse_args(["search", "q"])
        assert args.k == 5
        assert args.db == "chunks.db"
        assert not args.full
        assert not args.verbose

    def test_k_limits_output(self) -> None:
        code, out, _ = self._run("retries backoff", "--db", str(self.db),
                                 "--k", "1")
        assert code == 0
        assert "1 result(s) for:" in out

    def test_long_text_truncated_deterministically_by_default(self) -> None:
        code, out, _ = self._run("backoff jitter", "--db", str(self.db))
        assert code == 0
        assert "use --full" in out
        assert self.long_text not in out
        # Deterministic: identical invocation produces identical output.
        code2, out2, _ = self._run("backoff jitter", "--db", str(self.db))
        assert code2 == 0
        assert out == out2

    def test_full_flag_prints_complete_text(self) -> None:
        code, out, _ = self._run("backoff jitter", "--db", str(self.db),
                                 "--full")
        assert code == 0
        assert "use --full" not in out
        assert self.long_text in out

    def test_no_results_message_exits_zero(self) -> None:
        code, out, err = self._run("xylophone", "--db", str(self.db))
        assert code == 0
        assert "no results for: xylophone" in out
        assert err == ""

    def test_empty_query_exits_two(self) -> None:
        code, _, err = self._run("   ", "--db", str(self.db))
        assert code == 2
        assert "invalid search" in err

    def test_k_zero_exits_two(self) -> None:
        code, _, err = self._run("retries", "--db", str(self.db), "--k", "0")
        assert code == 2
        assert "invalid search" in err

    def test_missing_index_exits_two_with_rebuild_hint(self) -> None:
        missing = self.root / "missing.db"
        code, _, err = self._run("retries", "--db", str(missing))
        assert code == 2
        assert "python -m kba index" in err
        # The search must not create an empty database as a side effect.
        assert not missing.exists()

    def test_corrupt_index_exits_one(self) -> None:
        corrupt = self.root / "corrupt.db"
        corrupt.write_bytes(b"not a sqlite database at all")
        code, _, err = self._run("retries", "--db", str(corrupt))
        assert code == 1
        assert "error:" in err

    def test_verbose_reports_policy_on_stderr_without_sql_internals(self) -> None:
        code, out, err = self._run("How are retries handled?",
                                   "--db", str(self.db), "--verbose")
        assert code == 0
        # Verbose: policy/ranking/debug info an engineer can inspect.
        assert "policy: disjunction (OR)" in err
        assert "bm25" in err
        assert "higher = better" in err
        assert "k = 5" in err
        # Never expose SQL or implementation-specific types.
        for leak in ("SELECT", "MATCH ?", "sqlite3.", "chunks_fts"):
            assert leak not in err
        # Results remain on stdout and are unaffected.
        assert "result(s) for:" in out

    def test_abbreviated_section_shown_as_preamble(self) -> None:
        code, out, _ = self._run("backoff jitter", "--db", str(self.db),
                                 "--k", "3")
        assert code == 0
        assert "(preamble)" in out

    def test_search_leaves_index_bytes_unchanged(self) -> None:
        before = self.db.read_bytes()
        self._run("retries", "--db", str(self.db))
        assert self.db.read_bytes() == before


class TestSearchCliRealCorpus:
    """End-to-end: temp copy of the canonical corpus, representative query."""

    def test_search_real_corpus(self, tmp_path: Path) -> None:
        from kba.indexer import build_index, load_records

        chunks = tmp_path / "chunks.jsonl"
        chunks.write_bytes(REAL_CHUNKS.read_bytes())
        db = tmp_path / "chunks.db"
        build_index(load_records(chunks), db)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["search", "exponential backoff retry schedule",
                         "--db", str(db)])
        assert code == 0
        assert "networking-and-retries.md" in out.getvalue()
        assert "Retry Policy" in out.getvalue()
