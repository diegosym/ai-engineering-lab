"""Unit tests for the application retrieval layer (kba.retrieval)."""
from __future__ import annotations

import dataclasses
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kba.indexer import build_index, load_records
from kba.retrieval import (
    DEFAULT_K,
    IndexNotBuiltError,
    RetrievalError,
    SearchResult,
    retrieve,
    tokenize_query,
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


class TokenizeQueryTestCase(unittest.TestCase):
    def test_extracts_unicode_word_tokens(self) -> None:
        self.assertEqual(
            tokenize_query("  How are  retries handled? "),
            ("How", "are", "retries", "handled"),
        )

    def test_punctuation_and_syntax_characters_are_not_tokens(self) -> None:
        self.assertEqual(
            tokenize_query('"retries" AND * NEAR(3, backoff)'),
            ("retries", "AND", "NEAR", "3", "backoff"),
        )

    def test_returns_tuple_of_str(self) -> None:
        tokens = tokenize_query("retry policy")
        self.assertIsInstance(tokens, tuple)
        self.assertTrue(all(isinstance(t, str) for t in tokens))

    def test_empty_query_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            tokenize_query("")

    def test_whitespace_only_query_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            tokenize_query("   \t  ")

    def test_punctuation_only_query_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            tokenize_query("??? !!! ...")

    def test_non_string_query_raises_type_error(self) -> None:
        with self.assertRaises(TypeError):
            tokenize_query(123)  # type: ignore[arg-type]


class RetrieveContractTestCase(unittest.TestCase):
    """Fixture-backed tests of the retrieve(query, k) contract."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.db = self.root / "chunks.db"
        records = [
            make_record(0, text="alpha chunk about retries"),
            make_record(1, id="doc:1", text="beta chunk about backoff"),
            make_record(2, id="doc:2", text="gamma chunk about retries and backoff"),
            make_record(3, id="doc:3", text="delta chunk about jitters"),
        ]
        build_index(records, self.db)

    def test_returns_list_of_search_results(self) -> None:
        results = retrieve("retries backoff", 10, db_path=self.db)
        self.assertIsInstance(results, list)
        self.assertTrue(all(isinstance(r, SearchResult) for r in results))

    def test_result_fields_are_plain_data_only(self) -> None:
        results = retrieve("retries", 5, db_path=self.db)
        self.assertTrue(results)
        for r in results:
            self.assertIsInstance(r.id, str)
            self.assertIsInstance(r.source_file, str)
            self.assertIsInstance(r.section, str)
            self.assertIsInstance(r.text, str)
            self.assertIsInstance(r.score, float)

    def test_result_is_frozen(self) -> None:
        r = retrieve("retries", 1, db_path=self.db)[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.score = 0.0  # type: ignore[misc]

    def test_k_one_returns_exactly_one(self) -> None:
        results = retrieve("retries", 1, db_path=self.db)
        self.assertEqual(len(results), 1)

    def test_k_limits_results(self) -> None:
        results = retrieve("retries backoff", 2, db_path=self.db)
        self.assertLessEqual(len(results), 2)

    def test_fewer_matches_than_k_returns_all_without_padding(self) -> None:
        # "jitters" matches exactly one chunk; k=50 must not pad.
        results = retrieve("jitters", 50, db_path=self.db)
        self.assertEqual(len(results), 1)

    def test_all_matching_chunks_returned_when_k_large(self) -> None:
        # OR policy: "retries" OR "backoff" OR "jitters" matches all 4 chunks.
        results = retrieve("retries backoff jitters", 50, db_path=self.db)
        self.assertEqual(len(results), 4)

    def test_k_zero_negative_and_non_int_raise_value_error(self) -> None:
        for bad_k in (0, -1, 1.5, "5", None, True):  # noqa: B017
            with self.subTest(k=bad_k):
                with self.assertRaises(ValueError):
                    retrieve("retries", bad_k, db_path=self.db)  # type: ignore[arg-type]

    def test_empty_query_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            retrieve("", 5, db_path=self.db)

    def test_syntax_heavy_query_is_treated_as_literal_tokens(self) -> None:
        results = retrieve('retries " AND * NEAR(', 5, db_path=self.db)
        self.assertIsInstance(results, list)
        self.assertTrue(results)

    def test_scores_are_ordered_higher_is_better(self) -> None:
        results = retrieve("retries backoff", 10, db_path=self.db)
        scores = [r.score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_repeated_queries_are_deterministic(self) -> None:
        first = retrieve("retries backoff", 10, db_path=self.db)
        second = retrieve("retries backoff", 10, db_path=self.db)
        self.assertEqual(first, second)

    def test_equal_scores_tie_break_in_canonical_chunk_order(self) -> None:
        tie_db = self.root / "tie.db"
        body = "identical shared body mentioning retries"
        records = [
            make_record(0, id="tie:a", text=body),
            make_record(1, id="tie:b", text=body),
            make_record(2, id="tie:c", text=body),
        ]
        build_index(records, tie_db)
        results = retrieve("retries", 10, db_path=tie_db)
        self.assertEqual([r.id for r in results], ["tie:a", "tie:b", "tie:c"])
        self.assertEqual(len({r.score for r in results}), 1)

    def test_missing_index_raises_index_not_built_error(self) -> None:
        with self.assertRaises(IndexNotBuiltError):
            retrieve("retries", 5, db_path=self.root / "missing.db")
        # A missing index is a specific kind of retrieval failure.
        self.assertTrue(
            issubclass(IndexNotBuiltError, RetrievalError)
        )

    def test_corrupt_database_raises_retrieval_error(self) -> None:
        corrupt = self.root / "corrupt.db"
        corrupt.write_bytes(b"this is not a sqlite database")
        with self.assertRaises(RetrievalError):
            retrieve("retries", 5, db_path=corrupt)
        # It exists, so it must NOT be reported as a missing index.
        with self.assertRaises(RetrievalError) as ctx:
            retrieve("retries", 5, db_path=corrupt)
        self.assertNotIsInstance(ctx.exception, IndexNotBuiltError)

    def test_search_never_writes_to_the_index(self) -> None:
        before = self.db.read_bytes()
        retrieve("retries", 5, db_path=self.db)
        self.assertEqual(self.db.read_bytes(), before)

    def test_default_k_constant(self) -> None:
        self.assertEqual(DEFAULT_K, 5)


class ScoreSemanticsTestCase(unittest.TestCase):
    """Score = negated FTS5 bm25: higher is better, engine sign hidden."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        copy = self.root / "chunks.jsonl"
        copy.write_bytes(REAL_CHUNKS.read_bytes())
        self.db = self.root / "chunks.db"
        build_index(load_records(copy), self.db)

    def test_score_is_the_negation_of_fts5_bm25(self) -> None:
        # Independent calculation straight from the engine: the public
        # score must be exactly -bm25 (SQLite's negative convention hidden).
        with sqlite3.connect(self.db) as conn:
            row = conn.execute(
                """
                SELECT c.id, bm25(chunks_fts)
                FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid
                WHERE chunks_fts MATCH '"retries"'
                ORDER BY bm25(chunks_fts) ASC, chunks_fts.rowid ASC
                LIMIT 1
                """
            ).fetchone()
        results = retrieve("retries", 1, db_path=self.db)
        self.assertEqual(results[0].id, row[0])
        self.assertEqual(results[0].score, -row[1])
        self.assertGreater(results[0].score, 0)

    def test_scores_are_sorted_descending(self) -> None:
        results = retrieve("exponential backoff retry schedule", 5,
                           db_path=self.db)
        scores = [r.score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))


class RealCorpusQueryTestCase(unittest.TestCase):
    """Representative queries against a temp copy of the canonical corpus."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        copy = self.root / "chunks.jsonl"
        copy.write_bytes(REAL_CHUNKS.read_bytes())
        self.db = self.root / "chunks.db"
        build_index(load_records(copy), self.db)

    def _retrieve(self, query: str, k: int = 5) -> list[SearchResult]:
        return retrieve(query, k, db_path=self.db)

    def test_exact_relevant_query_ranks_expected_document_high(self) -> None:
        results = self._retrieve("exponential backoff retry schedule")
        self.assertTrue(results)
        top_sources = [r.source_file for r in results[:3]]
        self.assertIn("docs/corpus/networking-and-retries.md", top_sources)

    def test_multi_term_query_every_result_matches_a_query_token(self) -> None:
        query = "How are retries handled?"
        results = self._retrieve(query)
        self.assertTrue(results)
        tokens = [t.lower() for t in tokenize_query(query)]
        for r in results:
            self.assertTrue(
                any(t in r.text.lower() for t in tokens),
                msg=f"result {r.id} matches no query token",
            )

    def test_synonym_gap_query_returns_results_without_error(self) -> None:
        # Known lexical limitation: no synonym expansion. We assert the
        # search executes and returns well-formed results — not quality.
        results = self._retrieve("How do employees log in to the system?")
        self.assertTrue(results)
        for r in results:
            self.assertTrue(r.id and r.source_file and r.text)
            self.assertIsInstance(r.score, float)

    def test_near_miss_numeric_query_finds_expected_document(self) -> None:
        results = self._retrieve("What sampling interval does the gateway use?")
        self.assertTrue(results)
        sources = [r.source_file for r in results]
        self.assertIn("docs/corpus/edge-gateway-hardware.md", sources)

    def test_query_matching_nothing_returns_empty_list(self) -> None:
        self.assertEqual(self._retrieve("xylophone"), [])
        self.assertEqual(self._retrieve("xylophone", 10), [])


if __name__ == "__main__":
    unittest.main()
