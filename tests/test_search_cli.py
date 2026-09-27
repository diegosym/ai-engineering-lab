"""Tests for the ``python -m kba search`` CLI adapter (M2)."""
from __future__ import annotations

import contextlib
import io
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
        "text": f"Chunk {n} discusses retries and exponential backoff.",
    }
    record.update(overrides)
    return record


class SearchCliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.chunks = self.root / "chunks.jsonl"
        self.db = self.root / "chunks.db"
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
        self.assertEqual(code, 0)
        self.assertIn("result(s) for: retries", out)
        self.assertIn("docs/corpus/sample.md", out)
        self.assertIn("Section 0", out)
        self.assertIn("id: docs/corpus/sample.md:1-0", out)
        self.assertIn("discusses retries", out)
        self.assertEqual(err, "")

    def test_default_k_is_five(self) -> None:
        args = build_parser().parse_args(["search", "q"])
        self.assertEqual(args.k, 5)
        self.assertEqual(args.db, "chunks.db")
        self.assertFalse(args.full)
        self.assertFalse(args.verbose)

    def test_k_limits_output(self) -> None:
        code, out, _ = self._run("retries backoff", "--db", str(self.db),
                                 "--k", "1")
        self.assertEqual(code, 0)
        self.assertIn("1 result(s) for:", out)

    def test_long_text_truncated_deterministically_by_default(self) -> None:
        code, out, _ = self._run("backoff jitter", "--db", str(self.db))
        self.assertEqual(code, 0)
        self.assertIn("use --full", out)
        self.assertNotIn(self.long_text, out)
        # Deterministic: identical invocation produces identical output.
        code2, out2, _ = self._run("backoff jitter", "--db", str(self.db))
        self.assertEqual(code2, 0)
        self.assertEqual(out, out2)

    def test_full_flag_prints_complete_text(self) -> None:
        code, out, _ = self._run("backoff jitter", "--db", str(self.db),
                                 "--full")
        self.assertEqual(code, 0)
        self.assertNotIn("use --full", out)
        self.assertIn(self.long_text, out)

    def test_no_results_message_exits_zero(self) -> None:
        code, out, err = self._run("xylophone", "--db", str(self.db))
        self.assertEqual(code, 0)
        self.assertIn("no results for: xylophone", out)
        self.assertEqual(err, "")

    def test_empty_query_exits_two(self) -> None:
        code, _, err = self._run("   ", "--db", str(self.db))
        self.assertEqual(code, 2)
        self.assertIn("invalid search", err)

    def test_k_zero_exits_two(self) -> None:
        code, _, err = self._run("retries", "--db", str(self.db), "--k", "0")
        self.assertEqual(code, 2)
        self.assertIn("invalid search", err)

    def test_missing_index_exits_two_with_rebuild_hint(self) -> None:
        missing = self.root / "missing.db"
        code, _, err = self._run("retries", "--db", str(missing))
        self.assertEqual(code, 2)
        self.assertIn("python -m kba index", err)
        # The search must not create an empty database as a side effect.
        self.assertFalse(missing.exists())

    def test_corrupt_index_exits_one(self) -> None:
        corrupt = self.root / "corrupt.db"
        corrupt.write_bytes(b"not a sqlite database at all")
        code, _, err = self._run("retries", "--db", str(corrupt))
        self.assertEqual(code, 1)
        self.assertIn("error:", err)

    def test_verbose_reports_policy_on_stderr_without_sql_internals(self) -> None:
        code, out, err = self._run("How are retries handled?",
                                   "--db", str(self.db), "--verbose")
        self.assertEqual(code, 0)
        # Verbose: policy/ranking/debug info an engineer can inspect.
        self.assertIn("policy: disjunction (OR)", err)
        self.assertIn("bm25", err)
        self.assertIn("higher = better", err)
        self.assertIn("k = 5", err)
        # Never expose SQL or implementation-specific types.
        for leak in ("SELECT", "MATCH ?", "sqlite3.", "chunks_fts"):
            self.assertNotIn(leak, err)
        # Results remain on stdout and are unaffected.
        self.assertIn("result(s) for:", out)

    def test_abbreviated_section_shown_as_preamble(self) -> None:
        code, out, _ = self._run("backoff jitter", "--db", str(self.db),
                                 "--k", "3")
        self.assertEqual(code, 0)
        self.assertIn("(preamble)", out)

    def test_search_leaves_index_bytes_unchanged(self) -> None:
        before = self.db.read_bytes()
        self._run("retries", "--db", str(self.db))
        self.assertEqual(self.db.read_bytes(), before)


class SearchCliRealCorpusTestCase(unittest.TestCase):
    """End-to-end: temp copy of the canonical corpus, representative query."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_search_real_corpus(self) -> None:
        from kba.indexer import build_index, load_records

        chunks = self.root / "chunks.jsonl"
        chunks.write_bytes(REAL_CHUNKS.read_bytes())
        db = self.root / "chunks.db"
        build_index(load_records(chunks), db)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["search", "exponential backoff retry schedule",
                         "--db", str(db)])
        self.assertEqual(code, 0)
        self.assertIn("networking-and-retries.md", out.getvalue())
        self.assertIn("Retry Policy", out.getvalue())


if __name__ == "__main__":
    unittest.main()
