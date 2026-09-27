"""Tests for the M3 evaluation runner (``kba.evaluate``).

The runner is tested through injected fake retrievers — no FTS5 required.
The integration tests exercise ``temporary_fts5_retriever`` against a
synthetic chunks file in ``tmp_path`` only; the canonical corpus and golden
dataset are read (never modified) and the real baseline is not run here.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import kba.evaluate as evaluate_module
import kba.metrics
import kba.retrieval as retrieval_module
from kba.evaluate import (
    DEFAULT_GOLDEN_PATH,
    EvaluationSummary,
    GoldenQuery,
    QueryEvaluation,
    build_results_document,
    canonical_order_retriever,
    extract_ids,
    load_golden_dataset,
    run_evaluation,
    source_of_chunk_id,
    summarize,
    temporary_fts5_retriever,
)
from kba.retrieval import IndexNotBuiltError, SearchResult


def ranking(*chunk_ids: str) -> list[SearchResult]:
    """Build a fake ranked result list; higher rank position, lower score."""
    return [
        SearchResult(
            id=chunk_id,
            source_file=source_of_chunk_id(chunk_id),
            section="",
            text="",
            score=float(10 - rank),
        )
        for rank, chunk_id in enumerate(chunk_ids, start=1)
    ]


class RecordingRetriever:
    """Fake retriever: fixed ranking per query text; records every call."""

    def __init__(self, rankings: dict[str, tuple[str, ...]] | None = None) -> None:
        self.rankings = rankings or {}
        self.calls: list[tuple[str, int]] = []

    def __call__(self, query: str, k: int) -> list[SearchResult]:
        self.calls.append((query, k))
        return ranking(*self.rankings.get(query, ()))


class FailingRetriever:
    """Fake retriever that always fails — used for propagation tests."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def __call__(self, query: str, k: int) -> list[SearchResult]:
        raise self.error


@pytest.fixture
def dataset() -> list[GoldenQuery]:
    return [
        GoldenQuery("q01", "alpha query", "lexical-easy", ("doc1:1-5",)),
        GoldenQuery(
            "q02", "beta query", "cross-document", ("doc2:1-5", "doc3:1-5")
        ),
    ]


@pytest.fixture
def synthetic_chunks(tmp_path: Path, make_record) -> Path:
    """Synthetic corpus whose file order intentionally differs from sorted IDs.

    The canonical baseline must reproduce this file order exactly, which a
    sort by chunk ID would get wrong.
    """
    records = [
        make_record(
            3,
            id="docs/corpus/sample.md:10-14",
            text="The queue flushes every forty five seconds.",
        ),
        make_record(
            1,
            id="docs/corpus/sample.md:1-5",
            text="Gateway retries use exponential backoff schedule here.",
        ),
        make_record(
            2,
            id="docs/corpus/sample.md:6-9",
            text="Sampling interval for sensors is fifteen seconds.",
        ),
    ]
    path = tmp_path / "chunks.jsonl"
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    return path


class TestLoadGoldenDataset:
    def test_reads_the_frozen_golden_dataset(self) -> None:
        entries = load_golden_dataset(DEFAULT_GOLDEN_PATH)
        assert len(entries) == 18
        assert [entry.query_id for entry in entries] == [f"q{i:02d}" for i in range(1, 19)]
        by_id = {entry.query_id: entry for entry in entries}
        assert by_id["q12"].taxonomy == "lexical-easy"
        assert by_id["q03"].relevant_chunk_ids == (
            "docs/corpus/api-rate-limits.md:6-20",
            "docs/corpus/authentication-and-tokens.md:48-55",
        )

    def test_parses_required_fields(self, tmp_path: Path) -> None:
        path = tmp_path / "golden.jsonl"
        path.write_text(
            json.dumps(
                {
                    "id": "q01",
                    "query": "what?",
                    "taxonomy": "lexical-easy",
                    "relevant_chunk_ids": ["doc1:1-5"],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        entries = load_golden_dataset(path)
        assert entries == [
            GoldenQuery("q01", "what?", "lexical-easy", ("doc1:1-5",))
        ]

    def test_empty_file_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "golden.jsonl"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="no queries"):
            load_golden_dataset(path)

    def test_only_blank_lines_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "golden.jsonl"
        path.write_text("\n\n   \n", encoding="utf-8")
        with pytest.raises(ValueError, match="no queries"):
            load_golden_dataset(path)

    def test_invalid_json_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "golden.jsonl"
        path.write_text("{not json}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="line 1: invalid JSON"):
            load_golden_dataset(path)

    def test_missing_field_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "golden.jsonl"
        path.write_text(
            json.dumps({"id": "q01", "query": "what?", "taxonomy": "x"}) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="missing field"):
            load_golden_dataset(path)

    @pytest.mark.parametrize(
        "gold, match",
        [
            ("doc1:1-5", "non-empty list"),
            ([], "non-empty list"),
            ([7], "non-empty strings"),
            ([""], "non-empty strings"),
        ],
    )
    def test_bad_gold_is_rejected(
        self, tmp_path: Path, gold: object, match: str
    ) -> None:
        path = tmp_path / "golden.jsonl"
        path.write_text(
            json.dumps(
                {
                    "id": "q01",
                    "query": "what?",
                    "taxonomy": "x",
                    "relevant_chunk_ids": gold,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match=match):
            load_golden_dataset(path)

    def test_duplicate_query_id_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "golden.jsonl"
        line = json.dumps(
            {
                "id": "q01",
                "query": "what?",
                "taxonomy": "x",
                "relevant_chunk_ids": ["doc1:1-5"],
            }
        )
        path.write_text(line + "\n" + line + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate query id"):
            load_golden_dataset(path)

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_golden_dataset(tmp_path / "nope.jsonl")


class TestRunEvaluation:
    def test_runs_every_golden_query_with_a_fake_retriever(self) -> None:
        entries = load_golden_dataset(DEFAULT_GOLDEN_PATH)
        assert len({entry.query for entry in entries}) == 18
        retriever = RecordingRetriever(
            {entry.query: entry.relevant_chunk_ids for entry in entries}
        )
        run = run_evaluation(entries, retriever)
        assert len(retriever.calls) == 18
        assert [record.query_id for record in run.queries] == [
            entry.query_id for entry in entries
        ]
        # A perfect ranking scores 1.0 on every metric for every query.
        assert all(record.recall == 1.0 for record in run.queries)
        assert all(record.mrr == 1.0 for record in run.queries)
        assert all(record.ndcg == 1.0 for record in run.queries)
        assert all(record.source_recall == 1.0 for record in run.queries)

    def test_passes_default_k_five_to_retriever(self, dataset) -> None:
        retriever = RecordingRetriever()
        run = run_evaluation(dataset, retriever)
        assert retriever.calls == [("alpha query", 5), ("beta query", 5)]
        assert all(record.k == 5 for record in run.queries)

    def test_configured_k_reaches_retriever_and_metrics(self, dataset) -> None:
        retriever = RecordingRetriever(
            {"alpha query": ("doc9:1-5", "doc8:1-5", "doc7:1-5", "doc1:1-5")}
        )
        run = run_evaluation(dataset, retriever, k=3)
        assert retriever.calls[0] == ("alpha query", 3)
        record = run.queries[0]
        assert record.recall == 0.0          # gold sits at rank 4 > k=3
        assert record.mrr == pytest.approx(1 / 4)  # mrr scores the full ranking
        assert record.ndcg == 0.0
        assert run.k == 3 and record.k == 3

    def test_preserves_ranking_order(self, dataset) -> None:
        retriever = RecordingRetriever({"alpha query": ("doc3:1-5", "doc1:1-5", "doc2:1-5")})
        run = run_evaluation(dataset, retriever)
        assert run.queries[0].retrieved_chunk_ids == (
            "doc3:1-5",
            "doc1:1-5",
            "doc2:1-5",
        )

    def test_metrics_use_k_five_for_a_hit_at_rank_five(self, dataset) -> None:
        retriever = RecordingRetriever(
            {"alpha query": ("d9:1-5", "d8:1-5", "d7:1-5", "d6:1-5", "doc1:1-5")}
        )
        run = run_evaluation(dataset, retriever)
        record = run.queries[0]
        assert record.recall == 1.0
        assert record.mrr == pytest.approx(1 / 5)
        assert record.ndcg == pytest.approx((1 / math.log2(6)) / 1.0)

    def test_gold_after_top5_is_not_counted(self, dataset) -> None:
        retriever = RecordingRetriever(
            {
                "alpha query": (
                    "d9:1-5", "d8:1-5", "d7:1-5", "d6:1-5", "d5:1-5", "doc1:1-5",
                )
            }
        )
        run = run_evaluation(dataset, retriever)
        record = run.queries[0]
        assert record.recall == 0.0
        assert record.ndcg == 0.0
        assert record.mrr == pytest.approx(1 / 6)  # ranking itself was longer

    def test_source_level_recall_is_coarser_than_chunk_level(self) -> None:
        entries = [
            GoldenQuery(
                "q01", "alpha query", "lexical-easy", ("doc1:1-5", "doc1:9-12")
            )
        ]
        retriever = RecordingRetriever({"alpha query": ("doc1:1-5",)})
        run = run_evaluation(entries, retriever)
        record = run.queries[0]
        assert record.recall == 0.5     # one of two gold chunks
        assert record.source_recall == 1.0  # both golds share one source

    def test_one_record_per_query(self, dataset) -> None:
        run = run_evaluation(dataset, RecordingRetriever())
        assert len(run.queries) == len(dataset)
        assert {record.query_id for record in run.queries} == {"q01", "q02"}
        assert len({record.query_id for record in run.queries}) == 2

    def test_summary_is_the_macro_average(self, dataset) -> None:
        # q01 perfect, q02 empty ranking -> every mean is exactly 0.5.
        retriever = RecordingRetriever({"alpha query": ("doc1:1-5",)})
        run = run_evaluation(dataset, retriever)
        assert run.summary == EvaluationSummary(
            query_count=2, recall=0.5, mrr=0.5, ndcg=0.5, source_recall=0.5
        )
        assert run.summary == summarize(run.queries)

    def test_runner_is_deterministic(self, dataset) -> None:
        rankings = {"alpha query": ("doc1:1-5",), "beta query": ("doc2:1-5",)}
        first = run_evaluation(dataset, RecordingRetriever(rankings))
        second = run_evaluation(dataset, RecordingRetriever(dict(rankings)))
        assert first == second
        dump = lambda run: json.dumps(run.to_dict(), sort_keys=True)
        assert dump(first) == dump(second)

    def test_injected_retriever_is_the_one_used(self, dataset) -> None:
        retriever = RecordingRetriever({"alpha query": ("doc1:1-5",)})
        run_evaluation(dataset, retriever)
        assert retriever.calls == [("alpha query", 5), ("beta query", 5)]
        assert isinstance(retriever, RecordingRetriever)

    def test_retriever_failure_propagates(self, dataset) -> None:
        with pytest.raises(RuntimeError, match="boom"):
            run_evaluation(dataset, FailingRetriever(RuntimeError("boom")))

    def test_empty_dataset_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            run_evaluation([], RecordingRetriever())

    @pytest.mark.parametrize("k", [0, -1, 1.5, "5", None, True])
    def test_invalid_k_is_rejected_before_any_retrieval(self, dataset, k) -> None:
        retriever = RecordingRetriever()
        with pytest.raises(ValueError, match="k must be"):
            run_evaluation(dataset, retriever, k=k)
        assert retriever.calls == []


class TestAggregation:
    @staticmethod
    def _record(query_id: str, recall: float, mrr_v: float, ndcg_v: float, src: float):
        return QueryEvaluation(
            query_id=query_id,
            query="q",
            taxonomy="lexical-easy",
            relevant_chunk_ids=("doc1:1-5",),
            retrieved_chunk_ids=(),
            k=5,
            recall=recall,
            mrr=mrr_v,
            ndcg=ndcg_v,
            source_recall=src,
        )

    def test_summarize_computes_macro_means(self) -> None:
        summary = summarize(
            [
                self._record("q01", 1.0, 1.0, 1.0, 1.0),
                self._record("q02", 0.0, 0.0, 0.0, 0.5),
                self._record("q03", 0.5, 0.25, 0.75, 0.5),
            ]
        )
        assert summary.query_count == 3
        assert summary.recall == pytest.approx(1.5 / 3)
        assert summary.mrr == pytest.approx(1.25 / 3)
        assert summary.ndcg == pytest.approx(1.75 / 3)
        assert summary.source_recall == pytest.approx(2.0 / 3)

    def test_summarize_rejects_zero_queries(self) -> None:
        with pytest.raises(ValueError, match="zero queries"):
            summarize([])


class TestSerialization:
    def test_run_to_dict_exposes_every_required_field(self, dataset) -> None:
        retriever = RecordingRetriever({"alpha query": ("doc1:1-5",)})
        payload = run_evaluation(dataset, retriever).to_dict()
        assert set(payload) == {"k", "queries", "summary"}
        assert payload["k"] == 5
        record = payload["queries"][0]
        assert set(record) == {
            "query_id", "query", "taxonomy", "relevant_chunk_ids",
            "retrieved_chunk_ids", "k", "recall", "mrr", "ndcg", "source_recall",
        }
        assert set(payload["summary"]) == {
            "query_count", "recall", "mrr", "ndcg", "source_recall",
        }

    def test_to_dict_is_json_serializable(self, dataset) -> None:
        run = run_evaluation(dataset, RecordingRetriever())
        text = json.dumps(run.to_dict(), sort_keys=True)
        restored = json.loads(text)
        assert restored["queries"][0]["relevant_chunk_ids"] == ["doc1:1-5"]
        assert restored["summary"]["query_count"] == 2


class TestHelpers:
    def test_extract_ids_preserves_order(self) -> None:
        results = ranking("doc2:1-5", "doc1:1-5")
        assert extract_ids(results) == ["doc2:1-5", "doc1:1-5"]

    def test_source_of_chunk_id_matches_source_file(self) -> None:
        assert source_of_chunk_id("docs/corpus/api-rate-limits.md:6-20") == (
            "docs/corpus/api-rate-limits.md"
        )

    @pytest.mark.parametrize("chunk_id", ["nocolon", "a:1", ":1-5", 7, None])
    def test_source_of_chunk_id_rejects_malformed_ids(self, chunk_id) -> None:
        with pytest.raises(ValueError):
            source_of_chunk_id(chunk_id)


class TestFilesystemHygiene:
    def test_metrics_never_open_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*args, **kwargs):
            raise AssertionError("metric layer must not touch the filesystem")

        monkeypatch.setattr("builtins.open", _boom)
        gold = ("doc1:1-5",)
        retrieved = ["doc1:1-5", "doc2:1-5"]
        assert kba.metrics.recall_at_k(gold, retrieved, k=5) == 1.0
        assert kba.metrics.mrr(gold, retrieved) == 1.0
        assert kba.metrics.ndcg_at_k(gold, retrieved, k=5) == 1.0
        assert kba.metrics.source_recall(
            gold, retrieved, source_of_chunk_id
        ) == 1.0


class TestTemporaryFts5Retriever:
    def test_yields_a_real_retriever_over_a_synthetic_index(
        self, synthetic_chunks: Path
    ) -> None:
        with temporary_fts5_retriever(synthetic_chunks) as retriever:
            results = retriever("exponential backoff", 5)
        assert [result.id for result in results] == ["docs/corpus/sample.md:1-5"]
        assert all(isinstance(result, SearchResult) for result in results)

    def test_index_is_removed_when_the_context_exits(
        self, synthetic_chunks: Path
    ) -> None:
        with temporary_fts5_retriever(synthetic_chunks) as retriever:
            assert retriever("exponential backoff", 5)
        with pytest.raises(IndexNotBuiltError):
            retriever("exponential backoff", 5)

    def test_missing_chunks_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            with temporary_fts5_retriever(tmp_path / "nope.jsonl"):
                pass  # pragma: no cover - entry must fail first

    def test_end_to_end_run_is_byte_deterministic(
        self, synthetic_chunks: Path
    ) -> None:
        entries = [
            GoldenQuery(
                "q01", "exponential backoff schedule", "lexical-easy",
                ("docs/corpus/sample.md:1-5",),
            )
        ]

        def once() -> str:
            with temporary_fts5_retriever(synthetic_chunks) as retriever:
                run = run_evaluation(entries, retriever)
            return json.dumps(run.to_dict(), sort_keys=True)

        first, second = once(), once()
        assert first == second
        assert json.loads(first)["queries"][0]["recall"] == 1.0


class TestCanonicalOrderRetriever:
    def test_returns_the_first_k_chunks_in_canonical_file_order(
        self, synthetic_chunks: Path
    ) -> None:
        retriever = canonical_order_retriever(synthetic_chunks)
        results = retriever("anything at all", 3)
        # File order (3rd record first), not sorted-by-ID order.
        assert [result.id for result in results] == [
            "docs/corpus/sample.md:10-14",
            "docs/corpus/sample.md:1-5",
            "docs/corpus/sample.md:6-9",
        ]
        assert [result.score for result in results] == [0.0, 0.0, 0.0]

    def test_respects_k_without_padding(self, synthetic_chunks: Path) -> None:
        retriever = canonical_order_retriever(synthetic_chunks)
        assert [result.id for result in retriever("q", 2)] == [
            "docs/corpus/sample.md:10-14",
            "docs/corpus/sample.md:1-5",
        ]
        assert len(retriever("q", 10)) == 3  # k is a ceiling, no padding

    @pytest.mark.parametrize("k", [0, -1, "5"])
    def test_invalid_k_is_rejected(self, synthetic_chunks: Path, k) -> None:
        with pytest.raises(ValueError):
            canonical_order_retriever(synthetic_chunks)("q", k)

    def test_ranking_ignores_the_query_text(self, synthetic_chunks: Path) -> None:
        retriever = canonical_order_retriever(synthetic_chunks)
        first = [result.id for result in retriever("alpha beta", 5)]
        second = [result.id for result in retriever("totally different words", 5)]
        assert first == second


class TestBaselineIntegration:
    def test_both_baselines_flow_through_the_same_runner(
        self, synthetic_chunks: Path
    ) -> None:
        entries = [
            GoldenQuery(
                "q01", "exponential backoff schedule", "lexical-easy",
                ("docs/corpus/sample.md:1-5",),
            )
        ]
        with temporary_fts5_retriever(synthetic_chunks) as fts5:
            fts5_run = run_evaluation(entries, fts5)
        canonical_run = run_evaluation(
            entries, canonical_order_retriever(synthetic_chunks)
        )

        assert [r.query_id for r in fts5_run.queries] == ["q01"]
        assert [r.query_id for r in canonical_run.queries] == ["q01"]
        assert fts5_run.k == canonical_run.k == 5
        # Same runner, same record shape, two different rankings:
        assert fts5_run.queries[0].retrieved_chunk_ids == (
            "docs/corpus/sample.md:1-5",
        )
        assert canonical_run.queries[0].retrieved_chunk_ids == (
            "docs/corpus/sample.md:10-14",
            "docs/corpus/sample.md:1-5",
            "docs/corpus/sample.md:6-9",
        )
        assert set(fts5_run.to_dict()["queries"][0]) == set(
            canonical_run.to_dict()["queries"][0]
        )

    def test_canonical_never_calls_retrieve(
        self, synthetic_chunks: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(query: str, k: int):
            raise AssertionError("canonical baseline must not call retrieve()")

        monkeypatch.setattr(evaluate_module, "retrieve", _boom)
        entries = [
            GoldenQuery(
                "q01", "exponential backoff", "lexical-easy",
                ("docs/corpus/sample.md:1-5",),
            )
        ]
        run = run_evaluation(entries, canonical_order_retriever(synthetic_chunks))
        assert run.queries[0].retrieved_chunk_ids  # succeeded without retrieve()

    def test_fts5_baseline_uses_the_real_retrieval_function(self) -> None:
        assert evaluate_module.retrieve is retrieval_module.retrieve


class TestBuildResultsDocument:
    @pytest.fixture
    def two_runs(self, dataset: list[GoldenQuery]) -> dict:
        perfect = RecordingRetriever(
            {"alpha query": ("doc1:1-5",), "beta query": ("doc2:1-5", "doc3:1-5")}
        )
        weak = RecordingRetriever({"beta query": ("doc9:1-5",)})
        return {
            "fts5": run_evaluation(dataset, perfect),
            "canonical_order": run_evaluation(dataset, weak),
        }

    def test_exposes_the_required_structure(
        self, two_runs: dict, dataset: list[GoldenQuery]
    ) -> None:
        document = build_results_document(two_runs)
        assert set(document) == {
            "schema_version", "k", "metrics", "dataset", "corpus",
            "baselines", "results",
        }
        assert document["schema_version"] == 1
        assert document["k"] == 5
        assert document["metrics"] == {
            "chunk_level": ["recall@5", "mrr", "ndcg@5"],
            "source_level": ["source_recall"],
            "aggregation": "macro-mean over queries",
        }
        assert document["baselines"] == ["fts5", "canonical_order"]
        block = document["results"]["fts5"]
        assert set(block) == {"summary", "queries"}
        assert set(block["summary"]) == {
            "query_count", "recall", "mrr", "ndcg", "source_recall",
        }
        assert len(block["queries"]) == len(dataset)
        assert set(block["queries"][0]) == {
            "query_id", "query", "taxonomy", "relevant_chunk_ids",
            "retrieved_chunk_ids", "k", "recall", "mrr", "ndcg", "source_recall",
        }

    def test_fingerprints_the_frozen_inputs(self, two_runs: dict) -> None:
        document = build_results_document(two_runs)
        assert document["dataset"]["path"] == "docs/eval/golden-queries.jsonl"
        assert document["dataset"]["query_count"] == 2
        assert len(document["dataset"]["sha256"]) == 64
        assert document["corpus"]["path"] == "chunks.jsonl"
        assert document["corpus"]["chunk_count"] == 65  # frozen M3 corpus
        assert len(document["corpus"]["sha256"]) == 64

    def test_serialization_is_byte_deterministic(self, two_runs: dict) -> None:
        first = json.dumps(build_results_document(two_runs), sort_keys=True, indent=2)
        second = json.dumps(build_results_document(two_runs), sort_keys=True, indent=2)
        assert first == second
        assert json.loads(first)["baselines"] == ["fts5", "canonical_order"]

    def test_payload_carries_no_timestamps_or_machine_paths(
        self, two_runs: dict
    ) -> None:
        text = json.dumps(build_results_document(two_runs))
        assert "/Users/" not in text
        assert "/var/" not in text
        assert '"timestamp"' not in text and '"created_at"' not in text

    def test_no_runs_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="no baseline runs"):
            build_results_document({})

    def test_runs_must_share_one_k(self, dataset: list[GoldenQuery]) -> None:
        runs = {
            "a": run_evaluation(dataset, RecordingRetriever(), k=5),
            "b": run_evaluation(dataset, RecordingRetriever(), k=3),
        }
        with pytest.raises(ValueError, match="single k"):
            build_results_document(runs)

    def test_runs_must_cover_the_same_queries(
        self, dataset: list[GoldenQuery]
    ) -> None:
        runs = {
            "a": run_evaluation(dataset, RecordingRetriever()),
            "b": run_evaluation(dataset[:1], RecordingRetriever()),
        }
        with pytest.raises(ValueError, match="same queries"):
            build_results_document(runs)
