"""Validation tests for the M3 golden evaluation dataset.

Guards the structural invariants of ``docs/eval/golden-queries.jsonl`` so a
dataset edit cannot silently change the meaning of the evaluation: exactly 18
frozen queries, labels that exist literally in ``chunks.jsonl``, the approved
taxonomy distribution, and the q12 / q18 taxonomy decisions.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = REPO_ROOT / "docs" / "eval" / "golden-queries.jsonl"
CHUNKS_PATH = REPO_ROOT / "chunks.jsonl"
CORPUS_DIR = REPO_ROOT / "docs" / "corpus"

REQUIRED_FIELDS = (
    "id",
    "query",
    "taxonomy",
    "difficulty",
    "provenance",
    "relevant_chunk_ids",
    "distractor_chunk_ids",
    "source_docs",
    "rationale",
    "notes",
)
APPROVED_TAXONOMIES = {
    "lexical-easy",
    "synonym-gap",
    "cross-document",
    "numeric-near-miss",
    "generic-term-pollution",
    "overlapping-topics",
    "distractor-deprecated",
    "tokenization",
}
EXPECTED_DISTRIBUTION = {
    "lexical-easy": 4,
    "synonym-gap": 3,
    "cross-document": 3,
    "numeric-near-miss": 2,
    "generic-term-pollution": 2,
    "overlapping-topics": 2,
    "distractor-deprecated": 1,
    "tokenization": 1,
}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}
EXPECTED_IDS = [f"q{i:02d}" for i in range(1, 19)]

# Verbatim query text of the M2 spike cases (spike/m2-lexical-retrieval/NOTES.md, section D).
SPIKE_QUERY_TEXTS = {
    "q01": "How are retries handled?",
    "q02": "What sampling interval does the gateway use?",
    "q03": "How many requests per minute are allowed?",
    "q04": "How are engineers notified when something fails at night?",
    "q05": "What hardware does the CG-200 gateway use?",
    "q06": "Who do we escalate to when an incident drags on?",
    "q07": "What is the exponential backoff retry schedule?",
    "q08": "How do employees log in to the system?",
    "q09": "When does the ingestion pipeline flush queued batches?",
}


@pytest.fixture(scope="module")
def queries() -> list[dict]:
    lines = [
        line
        for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [json.loads(line) for line in lines]


@pytest.fixture(scope="module")
def chunk_sources() -> dict[str, str]:
    """Map every literal chunk ID in chunks.jsonl to its source document."""
    sources: dict[str, str] = {}
    with CHUNKS_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                sources[record["id"]] = record["source_file"]
    return sources


@pytest.fixture(scope="module")
def corpus_docs() -> set[str]:
    return {f"docs/corpus/{path.name}" for path in sorted(CORPUS_DIR.glob("*.md"))}


class TestDatasetStructure:
    def test_exactly_eighteen_queries(self, queries: list[dict]) -> None:
        assert len(queries) == 18

    def test_ids_are_unique(self, queries: list[dict]) -> None:
        ids = [q["id"] for q in queries]
        assert len(set(ids)) == len(ids)

    def test_ids_are_q01_to_q18_in_order(self, queries: list[dict]) -> None:
        assert [q["id"] for q in queries] == EXPECTED_IDS

    def test_every_query_has_required_fields(self, queries: list[dict]) -> None:
        for q in queries:
            for field in REQUIRED_FIELDS:
                assert field in q, f"{q.get('id', '?')} missing field {field!r}"

    def test_field_types(self, queries: list[dict]) -> None:
        for q in queries:
            assert isinstance(q["id"], str) and q["id"]
            assert isinstance(q["query"], str) and q["query"].strip()
            assert isinstance(q["taxonomy"], str)
            assert isinstance(q["difficulty"], str)
            assert isinstance(q["provenance"], str) and q["provenance"]
            assert isinstance(q["relevant_chunk_ids"], list)
            assert isinstance(q["distractor_chunk_ids"], list)
            assert isinstance(q["source_docs"], list)
            assert isinstance(q["rationale"], str) and q["rationale"].strip()
            assert isinstance(q["notes"], str) and q["notes"].strip()


class TestLabels:
    def test_taxonomy_in_approved_set(self, queries: list[dict]) -> None:
        for q in queries:
            assert q["taxonomy"] in APPROVED_TAXONOMIES, (
                f"{q['id']} has unapproved taxonomy {q['taxonomy']!r}"
            )

    def test_difficulty_is_valid(self, queries: list[dict]) -> None:
        for q in queries:
            assert q["difficulty"] in VALID_DIFFICULTIES, (
                f"{q['id']} has invalid difficulty {q['difficulty']!r}"
            )

    def test_relevant_ids_exist_in_chunks(
        self, queries: list[dict], chunk_sources: dict[str, str]
    ) -> None:
        for q in queries:
            for chunk_id in q["relevant_chunk_ids"]:
                assert chunk_id in chunk_sources, (
                    f"{q['id']} relevant chunk {chunk_id!r} not in chunks.jsonl"
                )

    def test_distractor_ids_exist_in_chunks(
        self, queries: list[dict], chunk_sources: dict[str, str]
    ) -> None:
        for q in queries:
            for chunk_id in q["distractor_chunk_ids"]:
                assert chunk_id in chunk_sources, (
                    f"{q['id']} distractor chunk {chunk_id!r} not in chunks.jsonl"
                )

    def test_between_one_and_three_relevant_chunks(
        self, queries: list[dict]
    ) -> None:
        for q in queries:
            count = len(q["relevant_chunk_ids"])
            assert 1 <= count <= 3, f"{q['id']} has {count} relevant chunks"

    def test_no_duplicate_relevant_ids_within_query(
        self, queries: list[dict]
    ) -> None:
        for q in queries:
            ids = q["relevant_chunk_ids"]
            assert len(set(ids)) == len(ids), f"{q['id']} repeats a relevant ID"

    def test_relevant_and_distractor_labels_do_not_overlap(
        self, queries: list[dict]
    ) -> None:
        for q in queries:
            overlap = set(q["relevant_chunk_ids"]) & set(q["distractor_chunk_ids"])
            assert not overlap, f"{q['id']} labels {overlap} both relevant and distractor"


class TestSourceDocs:
    def test_source_docs_match_relevant_chunks(
        self, queries: list[dict], chunk_sources: dict[str, str]
    ) -> None:
        for q in queries:
            derived = {
                chunk_sources[chunk_id] for chunk_id in q["relevant_chunk_ids"]
            }
            assert set(q["source_docs"]) == derived, (
                f"{q['id']} source_docs {q['source_docs']} != derived {sorted(derived)}"
            )

    def test_source_docs_are_corpus_files(
        self, queries: list[dict], corpus_docs: set[str]
    ) -> None:
        for q in queries:
            for doc in q["source_docs"]:
                assert doc in corpus_docs, f"{q['id']} source_doc {doc!r} outside corpus"

    def test_all_ten_corpus_documents_are_covered(
        self, queries: list[dict], corpus_docs: set[str]
    ) -> None:
        covered = {doc for q in queries for doc in q["source_docs"]}
        assert len(corpus_docs) == 10, "corpus is expected to hold 10 documents"
        assert covered == corpus_docs, (
            f"missing {sorted(corpus_docs - covered)}, extra {sorted(covered - corpus_docs)}"
        )


class TestDistribution:
    def test_taxonomy_distribution_matches_approved(
        self, queries: list[dict]
    ) -> None:
        distribution = dict(Counter(q["taxonomy"] for q in queries))
        assert distribution == EXPECTED_DISTRIBUTION

    def test_q12_is_lexical_easy(self, queries: list[dict]) -> None:
        by_id = {q["id"]: q for q in queries}
        assert by_id["q12"]["taxonomy"] == "lexical-easy"

    def test_q18_is_the_only_tokenization_query(
        self, queries: list[dict]
    ) -> None:
        tokenization = [q["id"] for q in queries if q["taxonomy"] == "tokenization"]
        assert tokenization == ["q18"]


class TestProvenance:
    def test_q01_to_q09_keep_m2_spike_provenance(
        self, queries: list[dict]
    ) -> None:
        by_id = {q["id"]: q for q in queries}
        for number in range(1, 10):
            query_id = f"q{number:02d}"
            assert by_id[query_id]["provenance"] == f"m2-spike-q{number}"

    def test_q01_to_q09_keep_spike_query_text_verbatim(
        self, queries: list[dict]
    ) -> None:
        by_id = {q["id"]: q for q in queries}
        for query_id, expected in SPIKE_QUERY_TEXTS.items():
            assert by_id[query_id]["query"] == expected

    def test_q10_to_q18_have_new_provenance(self, queries: list[dict]) -> None:
        by_id = {q["id"]: q for q in queries}
        for number in range(10, 19):
            query_id = f"q{number:02d}"
            assert by_id[query_id]["provenance"] == "new"
