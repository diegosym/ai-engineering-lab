"""End-to-end tests: real corpus -> chunks.jsonl -> acceptance assertions."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kba.__main__ import main

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "docs" / "corpus"
EXPECTED_FIELDS = ["id", "source_file", "format", "title", "section",
                   "chunk_index", "chunk_count", "start_line", "end_line",
                   "char_count", "text"]
PINNED_CHUNK_COUNT = 65  # 55 H2 sections + 10 preambles on the M0 corpus


def corpus_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\n")


@pytest.fixture(scope="module")
def ingest_run(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """Run ingestion ONCE against the real corpus; share the result.

    Module scope preserves the original setUpClass semantics: one run,
    shared by all tests in this module; cleaned up when the module ends.
    """
    tmp = tmp_path_factory.mktemp("ingest_e2e")
    out = tmp / "chunks.jsonl"
    exit_code = main(["ingest", "--corpus", str(CORPUS), "--out", str(out)])
    records = [json.loads(line)
               for line in out.read_text(encoding="utf-8").splitlines()]
    return SimpleNamespace(out=out, exit_code=exit_code, records=records)


class TestIngestionRun:
    def test_exit_zero_and_all_ten_files_present(
            self, ingest_run: SimpleNamespace) -> None:
        assert ingest_run.exit_code == 0
        sources = {r["source_file"] for r in ingest_run.records}
        assert len(sources) == 10

    def test_pinned_chunk_count(self, ingest_run: SimpleNamespace) -> None:
        assert len(ingest_run.records) == PINNED_CHUNK_COUNT
        assert len(ingest_run.records) >= 65

    def test_every_h2_section_of_every_file_present(
            self, ingest_run: SimpleNamespace) -> None:
        expected = set()
        for path in sorted(CORPUS.glob("*.md")):
            rel = path.relative_to(REPO).as_posix()
            for line in corpus_lines(path):
                if line.startswith("## "):
                    expected.add((rel, line[3:].strip()))
        actual = {(r["source_file"], r["section"])
                  for r in ingest_run.records}
        missing = expected - actual
        assert not missing, f"sections missing: {missing}"

    def test_preamble_section_is_empty_string_for_all_files(
            self, ingest_run: SimpleNamespace) -> None:
        preamble_files = {r["source_file"] for r in ingest_run.records
                          if r["section"] == ""}
        assert len(preamble_files) == 10


class TestRecordIntegrity:
    def test_all_eleven_fields_with_correct_types(
            self, ingest_run: SimpleNamespace) -> None:
        for record in ingest_run.records:
            assert list(record.keys()) == EXPECTED_FIELDS
            for key in ("id", "source_file", "format", "title", "section",
                        "text"):
                assert isinstance(record[key], str)
            for key in ("chunk_index", "chunk_count", "start_line",
                        "end_line", "char_count"):
                assert isinstance(record[key], int)
            assert record["char_count"] == len(record["text"])

    def test_ids_unique(self, ingest_run: SimpleNamespace) -> None:
        ids = [r["id"] for r in ingest_run.records]
        assert len(ids) == len(set(ids))

    def test_line_ranges_valid_within_source_files(
            self, ingest_run: SimpleNamespace) -> None:
        for record in ingest_run.records:
            path = REPO / record["source_file"]
            total = len(corpus_lines(path))
            assert record["start_line"] <= record["end_line"]
            assert record["start_line"] >= 1
            assert record["end_line"] <= total

    def test_sources_all_under_corpus_and_never_the_plan(
            self, ingest_run: SimpleNamespace) -> None:
        prefix = os.path.relpath(CORPUS, REPO).replace(os.sep, "/") + "/"
        for record in ingest_run.records:
            assert record["source_file"].startswith(prefix), \
                record["source_file"]
            assert "project-plan" not in record["source_file"]

    def test_chunk_index_and_count_consistency(
            self, ingest_run: SimpleNamespace) -> None:
        per_file: dict[str, list[dict]] = {}
        for record in ingest_run.records:
            per_file.setdefault(record["source_file"], []).append(record)
        for source, records in per_file.items():
            indices = [r["chunk_index"] for r in records]
            assert indices == list(range(len(records))), source
            for record in records:
                assert record["chunk_count"] == len(records), source


def _runs(path: Path, predicate) -> list[tuple[int, int]]:
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


class TestStructuralIntegrity:
    def test_no_chunk_splits_a_table(
            self, ingest_run: SimpleNamespace) -> None:
        for path in sorted(CORPUS.glob("*.md")):
            rel = path.relative_to(REPO).as_posix()
            file_records = [r for r in ingest_run.records
                            if r["source_file"] == rel]
            for run_start, run_end in _runs(
                    path, lambda line: line.startswith("|")):
                assert any(r["start_line"] <= run_start
                           and run_end <= r["end_line"]
                           for r in file_records), \
                    f"table run {run_start}-{run_end} not contained " \
                    f"in one chunk of {rel}"

    def test_no_chunk_splits_a_fenced_code_block(
            self, ingest_run: SimpleNamespace) -> None:
        for path in sorted(CORPUS.glob("*.md")):
            rel = path.relative_to(REPO).as_posix()
            file_records = [r for r in ingest_run.records
                            if r["source_file"] == rel]
            in_fence = False
            start = 0
            for line_no, line in enumerate(corpus_lines(path), start=1):
                if not line.startswith("```"):
                    continue
                if not in_fence:
                    in_fence, start = True, line_no
                else:
                    assert any(r["start_line"] <= start
                               and line_no <= r["end_line"]
                               for r in file_records), \
                        f"fence {start}-{line_no} split across chunks " \
                        f"in {rel}"
                    in_fence = False


class TestRetrievalChallengeIntegrity:
    def test_retry_policy_chunk_contains_canonical_answer(
            self, ingest_run: SimpleNamespace) -> None:
        matches = [r for r in ingest_run.records
                   if r["section"] == "Retry Policy"
                   and "exponential backoff" in r["text"]]
        assert len(matches) == 1

    def test_deprecated_section_verbatim(
            self, ingest_run: SimpleNamespace) -> None:
        matches = [r for r in ingest_run.records
                   if r["section"] ==
                   "Deprecated: Legacy Rollback Procedure (superseded)"]
        assert len(matches) == 1
        assert "DEPRECATED" in matches[0]["text"]

    def test_near_miss_numbers_stay_in_distinct_files(
            self, ingest_run: SimpleNamespace) -> None:
        fast = {r["source_file"] for r in ingest_run.records
                if "600 requests per minute" in r["text"]}
        slow = {r["source_file"] for r in ingest_run.records
                if "60 requests per minute" in r["text"]}
        assert fast and slow
        assert not fast & slow

    def test_split_answer_spans_two_documents(
            self, ingest_run: SimpleNamespace) -> None:
        replay = {r["source_file"] for r in ingest_run.records
                  if "24 hours" in r["text"]}
        retention = {r["source_file"] for r in ingest_run.records
                     if "35 days" in r["text"]}
        assert any("ingestion-pipeline" in s for s in replay)
        assert any("storage-and-retention" in s for s in retention)


class TestDeterminismAndCli:
    def test_two_runs_are_byte_identical(self, tmp_path: Path) -> None:
        out1 = tmp_path / "one.jsonl"
        out2 = tmp_path / "two.jsonl"
        assert main(["ingest", "--corpus", str(CORPUS),
                     "--out", str(out1)]) == 0
        assert main(["ingest", "--corpus", str(CORPUS),
                     "--out", str(out2)]) == 0
        assert out1.read_bytes() == out2.read_bytes()

    def test_overlap_zero_and_custom_flags_accepted(
            self, tmp_path: Path) -> None:
        out = tmp_path / "c.jsonl"
        code = main(["ingest", "--corpus", str(CORPUS), "--out", str(out),
                     "--chunk-size", "800", "--overlap", "0"])
        assert code == 0
        records = [json.loads(l) for l in
                   out.read_text(encoding="utf-8").splitlines()]
        assert len(records) >= 65

    def test_invalid_overlap_exits_2(self) -> None:
        assert main(["ingest", "--chunk-size", "100",
                     "--overlap", "100"]) == 2
        assert main(["ingest", "--chunk-size", "100",
                     "--overlap", "-5"]) == 2

    def test_missing_corpus_exits_2(self) -> None:
        assert main(["ingest", "--corpus",
                     "/nonexistent/corpus/dir"]) == 2

    def test_undecodable_file_fails_run_with_exit_1(
            self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.md"
        bad.write_bytes(b"\xff\xfe broken \x80")
        out = tmp_path / "chunks.jsonl"
        assert main(["ingest", "--corpus", str(tmp_path),
                     "--out", str(out)]) == 1
        assert not out.exists()

    def test_txt_file_end_to_end(self, tmp_path: Path) -> None:
        txt = tmp_path / "notes.txt"
        txt.write_text("alpha beta\n\ngamma delta\n", encoding="utf-8")
        out = tmp_path / "chunks.jsonl"
        assert main(["ingest", "--corpus", str(tmp_path),
                     "--out", str(out)]) == 0
        records = [json.loads(l) for l in
                   out.read_text(encoding="utf-8").splitlines()]
        assert len(records) == 1
        assert records[0]["format"] == "txt"
        assert records[0]["title"] == "notes"
        assert records[0]["section"] == ""
