"""End-to-end tests: real corpus -> chunks.jsonl -> acceptance assertions."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from kba.__main__ import main

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "docs" / "corpus"
EXPECTED_FIELDS = ["id", "source_file", "format", "title", "section",
                   "chunk_index", "chunk_count", "start_line", "end_line",
                   "char_count", "text"]
PINNED_CHUNK_COUNT = 65  # 55 H2 sections + 10 preambles on the M0 corpus


def corpus_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\n")


class IngestE2ETestCase(unittest.TestCase):
    """Run ingestion once against the real corpus; share the result."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "chunks.jsonl"
        cls.exit_code = main(["ingest", "--corpus", str(CORPUS),
                              "--out", str(cls.out)])
        cls.records = [json.loads(line)
                       for line in cls.out.read_text(encoding="utf-8")
                       .splitlines()]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()


class IngestionRunTests(IngestE2ETestCase):
    def test_exit_zero_and_all_ten_files_present(self) -> None:
        self.assertEqual(self.exit_code, 0)
        sources = {r["source_file"] for r in self.records}
        self.assertEqual(len(sources), 10)

    def test_pinned_chunk_count(self) -> None:
        self.assertEqual(len(self.records), PINNED_CHUNK_COUNT)
        self.assertGreaterEqual(len(self.records), 65)

    def test_every_h2_section_of_every_file_present(self) -> None:
        expected = set()
        for path in sorted(CORPUS.glob("*.md")):
            rel = path.relative_to(REPO).as_posix()
            for line in corpus_lines(path):
                if line.startswith("## "):
                    expected.add((rel, line[3:].strip()))
        actual = {(r["source_file"], r["section"]) for r in self.records}
        missing = expected - actual
        self.assertFalse(missing, f"sections missing: {missing}")

    def test_preamble_section_is_empty_string_for_all_files(self) -> None:
        preamble_files = {r["source_file"] for r in self.records
                          if r["section"] == ""}
        self.assertEqual(len(preamble_files), 10)


class RecordIntegrityTests(IngestE2ETestCase):
    def test_all_eleven_fields_with_correct_types(self) -> None:
        for record in self.records:
            self.assertEqual(list(record.keys()), EXPECTED_FIELDS)
            for key in ("id", "source_file", "format", "title", "section",
                        "text"):
                self.assertIsInstance(record[key], str)
            for key in ("chunk_index", "chunk_count", "start_line",
                        "end_line", "char_count"):
                self.assertIsInstance(record[key], int)
            self.assertEqual(record["char_count"], len(record["text"]))

    def test_ids_unique(self) -> None:
        ids = [r["id"] for r in self.records]
        self.assertEqual(len(ids), len(set(ids)))

    def test_line_ranges_valid_within_source_files(self) -> None:
        for record in self.records:
            path = REPO / record["source_file"]
            total = len(corpus_lines(path))
            self.assertLessEqual(record["start_line"], record["end_line"])
            self.assertGreaterEqual(record["start_line"], 1)
            self.assertLessEqual(record["end_line"], total)

    def test_sources_all_under_corpus_and_never_the_plan(self) -> None:
        prefix = os.path.relpath(CORPUS, REPO).replace(os.sep, "/") + "/"
        for record in self.records:
            self.assertTrue(record["source_file"].startswith(prefix),
                            record["source_file"])
            self.assertNotIn("project-plan", record["source_file"])

    def test_chunk_index_and_count_consistency(self) -> None:
        per_file: dict[str, list[dict]] = {}
        for record in self.records:
            per_file.setdefault(record["source_file"], []).append(record)
        for source, records in per_file.items():
            indices = [r["chunk_index"] for r in records]
            self.assertEqual(indices, list(range(len(records))), source)
            for record in records:
                self.assertEqual(record["chunk_count"], len(records), source)


class StructuralIntegrityTests(IngestE2ETestCase):
    def _runs(self, path: Path, predicate) -> list[tuple[int, int]]:
        """Contiguous 1-based line runs where *predicate* holds."""
        runs: list[tuple[int, int]] = []
        start = None
        for line_no, line in enumerate(corpus_lines(path), start=1):
            if predicate(line):
                if start is None:
                    start = line_no
            elif start is not None:
                runs.append((start, line_no - 1))
                start = None
        if start is not None:
            runs.append((start, len(corpus_lines(path))))
        return runs

    def test_no_chunk_splits_a_table(self) -> None:
        for path in sorted(CORPUS.glob("*.md")):
            rel = path.relative_to(REPO).as_posix()
            file_records = [r for r in self.records
                            if r["source_file"] == rel]
            for run_start, run_end in self._runs(
                    path, lambda line: line.startswith("|")):
                self.assertTrue(
                    any(r["start_line"] <= run_start
                        and run_end <= r["end_line"]
                        for r in file_records),
                    f"table run {run_start}-{run_end} not contained "
                    f"in one chunk of {rel}")

    def test_no_chunk_splits_a_fenced_code_block(self) -> None:
        for path in sorted(CORPUS.glob("*.md")):
            rel = path.relative_to(REPO).as_posix()
            file_records = [r for r in self.records
                            if r["source_file"] == rel]
            in_fence = False
            start = 0
            for line_no, line in enumerate(corpus_lines(path), start=1):
                if not line.startswith("```"):
                    continue
                if not in_fence:
                    in_fence, start = True, line_no
                else:
                    self.assertTrue(
                        any(r["start_line"] <= start
                            and line_no <= r["end_line"]
                            for r in file_records),
                        f"fence {start}-{line_no} split across chunks "
                        f"in {rel}")
                    in_fence = False


class RetrievalChallengeIntegrityTests(IngestE2ETestCase):
    def test_retry_policy_chunk_contains_canonical_answer(self) -> None:
        matches = [r for r in self.records
                   if r["section"] == "Retry Policy"
                   and "exponential backoff" in r["text"]]
        self.assertEqual(len(matches), 1)

    def test_deprecated_section_verbatim(self) -> None:
        matches = [r for r in self.records
                   if r["section"] ==
                   "Deprecated: Legacy Rollback Procedure (superseded)"]
        self.assertEqual(len(matches), 1)
        self.assertIn("DEPRECATED", matches[0]["text"])

    def test_near_miss_numbers_stay_in_distinct_files(self) -> None:
        fast = {r["source_file"] for r in self.records
                if "600 requests per minute" in r["text"]}
        slow = {r["source_file"] for r in self.records
                if "60 requests per minute" in r["text"]}
        self.assertTrue(fast and slow)
        self.assertFalse(fast & slow)

    def test_split_answer_spans_two_documents(self) -> None:
        replay = {r["source_file"] for r in self.records
                  if "24 hours" in r["text"]}
        retention = {r["source_file"] for r in self.records
                     if "35 days" in r["text"]}
        self.assertTrue(any("ingestion-pipeline" in s for s in replay))
        self.assertTrue(any("storage-and-retention" in s for s in retention))


class DeterminismAndCliTests(unittest.TestCase):
    def test_two_runs_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out1 = Path(tmp) / "one.jsonl"
            out2 = Path(tmp) / "two.jsonl"
            self.assertEqual(main(["ingest", "--corpus", str(CORPUS),
                                   "--out", str(out1)]), 0)
            self.assertEqual(main(["ingest", "--corpus", str(CORPUS),
                                   "--out", str(out2)]), 0)
            self.assertEqual(out1.read_bytes(), out2.read_bytes())

    def test_overlap_zero_and_custom_flags_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "c.jsonl"
            code = main(["ingest", "--corpus", str(CORPUS), "--out", str(out),
                         "--chunk-size", "800", "--overlap", "0"])
            self.assertEqual(code, 0)
            records = [json.loads(l) for l in
                       out.read_text(encoding="utf-8").splitlines()]
            self.assertGreaterEqual(len(records), 65)

    def test_invalid_overlap_exits_2(self) -> None:
        self.assertEqual(main(["ingest", "--chunk-size", "100",
                               "--overlap", "100"]), 2)
        self.assertEqual(main(["ingest", "--chunk-size", "100",
                               "--overlap", "-5"]), 2)

    def test_missing_corpus_exits_2(self) -> None:
        self.assertEqual(main(["ingest", "--corpus",
                               "/nonexistent/corpus/dir"]), 2)

    def test_undecodable_file_fails_run_with_exit_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.md"
            bad.write_bytes(b"\xff\xfe broken \x80")
            out = Path(tmp) / "chunks.jsonl"
            self.assertEqual(main(["ingest", "--corpus", tmp,
                                   "--out", str(out)]), 1)
            self.assertFalse(out.exists())

    def test_txt_file_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            txt = Path(tmp) / "notes.txt"
            txt.write_text("alpha beta\n\ngamma delta\n", encoding="utf-8")
            out = Path(tmp) / "chunks.jsonl"
            self.assertEqual(main(["ingest", "--corpus", tmp,
                                   "--out", str(out)]), 0)
            records = [json.loads(l) for l in
                       out.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["format"], "txt")
            self.assertEqual(records[0]["title"], "notes")
            self.assertEqual(records[0]["section"], "")


if __name__ == "__main__":
    unittest.main()
