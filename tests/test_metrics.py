"""Deterministic tests for the pure retrieval metrics in ``kba.metrics``.

Every expectation states the arithmetic explicitly (``1/5``, ``2/3``, or the
manual ``dcg``/``idcg`` fractions), so a failure shows the intended math
directly instead of a re-implementation of the metric under test.
"""
from __future__ import annotations

import math

import pytest

from kba.metrics import mrr, ndcg_at_k, recall_at_k, source_recall


def source_of(chunk_id: str) -> str:
    """Test IDs look like ``doc1:1-5``; the source document is the prefix."""
    return chunk_id.split(":", 1)[0]


def dcg_at(hit_ranks: list[int]) -> float:
    """Binary DCG for hits at the given 1-based ranks."""
    return sum(1.0 / math.log2(rank + 1) for rank in hit_ranks)


def idcg_at(num_gold: int, k: int) -> float:
    """Binary IDCG@k: the ``num_gold`` best ranks, capped at ``k``."""
    top = min(k, num_gold)
    return sum(1.0 / math.log2(rank + 1) for rank in range(1, top + 1))


def apply_metric(name: str, gold, retrieved) -> float:
    if name == "recall_at_k":
        return recall_at_k(gold, retrieved, k=5)
    if name == "mrr":
        return mrr(gold, retrieved)
    if name == "ndcg_at_k":
        return ndcg_at_k(gold, retrieved, k=5)
    if name == "source_recall":
        return source_recall(gold, retrieved, source_of)
    raise AssertionError(f"unknown metric {name!r}")


METRIC_NAMES = ["recall_at_k", "mrr", "ndcg_at_k", "source_recall"]


class TestRecallAtK:
    def test_all_relevant_recovered(self) -> None:
        assert recall_at_k({"a", "b"}, ["a", "b", "x"]) == 1.0

    def test_none_recovered(self) -> None:
        assert recall_at_k({"a", "b"}, ["x", "y", "z"]) == 0.0

    def test_some_relevant_recovered(self) -> None:
        assert recall_at_k({"a", "b", "c"}, ["a", "x", "b", "y"]) == pytest.approx(2 / 3)

    def test_relevant_at_rank_five_counts(self) -> None:
        assert recall_at_k({"a"}, ["x1", "x2", "x3", "x4", "a"]) == 1.0

    def test_relevant_after_top5_is_ignored(self) -> None:
        assert recall_at_k({"a"}, ["x1", "x2", "x3", "x4", "x5", "a"]) == 0.0

    def test_empty_retrieved_returns_zero(self) -> None:
        assert recall_at_k({"a", "b"}, []) == 0.0

    @pytest.mark.parametrize("retrieved, expected", [
        (["a"], 1.0),
        (["x", "a"], 1.0),
        (["x"], 0.0),
        ([], 0.0),
    ])
    def test_single_gold_chunk(self, retrieved: list[str], expected: float) -> None:
        assert recall_at_k({"a"}, retrieved) == expected

    @pytest.mark.parametrize("k, expected", [
        (1, 1 / 4),
        (2, 1 / 4),
        (3, 2 / 4),
        (5, 3 / 4),
        (7, 4 / 4),
    ])
    def test_k_is_configurable(self, k: int, expected: float) -> None:
        gold = {"a", "b", "c", "d"}
        retrieved = ["a", "x1", "b", "x2", "c", "x3", "d"]
        assert recall_at_k(gold, retrieved, k=k) == pytest.approx(expected)

    def test_default_k_is_five(self) -> None:
        gold = {"a", "b"}
        retrieved = ["a", "x1", "x2", "x3", "x4", "b"]
        assert recall_at_k(gold, retrieved) == recall_at_k(gold, retrieved, k=5)

    def test_duplicate_gold_ids_collapse_into_a_set(self) -> None:
        assert recall_at_k(["a", "a", "b"], ["a"]) == 0.5


class TestMRR:
    def test_relevant_at_position_one(self) -> None:
        assert mrr({"a"}, ["a", "x"]) == 1.0

    def test_relevant_at_position_five(self) -> None:
        assert mrr({"a"}, ["x1", "x2", "x3", "x4", "a"]) == pytest.approx(1 / 5)

    def test_relevant_after_top5_still_scores(self) -> None:
        assert mrr({"a"}, ["x1", "x2", "x3", "x4", "x5", "a"]) == pytest.approx(1 / 6)

    def test_none_recovered(self) -> None:
        assert mrr({"a"}, ["x", "y"]) == 0.0

    def test_empty_retrieved_returns_zero(self) -> None:
        assert mrr({"a", "b"}, []) == 0.0

    @pytest.mark.parametrize("retrieved, expected", [
        (["a", "x", "b"], 1.0),
        (["x", "a", "b"], 1 / 2),
        (["x", "y", "a"], 1 / 3),
    ])
    def test_first_hit_among_multiple_golds(
        self, retrieved: list[str], expected: float
    ) -> None:
        assert mrr({"a", "b"}, retrieved) == pytest.approx(expected)


class TestNDCGAtK:
    def test_perfect_ranking_scores_one(self) -> None:
        assert ndcg_at_k({"a", "b"}, ["a", "b", "x"]) == 1.0

    def test_none_recovered(self) -> None:
        assert ndcg_at_k({"a", "b"}, ["x", "y"]) == 0.0

    def test_empty_retrieved_returns_zero(self) -> None:
        assert ndcg_at_k({"a", "b"}, []) == 0.0

    def test_single_gold_at_rank_one_scores_one(self) -> None:
        assert ndcg_at_k({"a"}, ["a"]) == 1.0

    def test_partial_hits_match_manual_ndcg(self) -> None:
        # gold {a, b}; hits at ranks 2 and 3 of a top-5 ranking.
        gold = {"a", "b"}
        retrieved = ["x", "a", "b"]
        expected = dcg_at([2, 3]) / idcg_at(num_gold=2, k=5)
        assert ndcg_at_k(gold, retrieved, k=5) == pytest.approx(expected)

    def test_hit_at_rank_five_is_discounted(self) -> None:
        retrieved = ["x1", "x2", "x3", "x4", "a"]
        expected = dcg_at([5]) / idcg_at(num_gold=1, k=5)
        assert ndcg_at_k({"a"}, retrieved) == pytest.approx(expected)

    def test_hit_after_top5_scores_zero(self) -> None:
        assert ndcg_at_k({"a"}, ["x1", "x2", "x3", "x4", "x5", "a"]) == 0.0

    def test_idcg_is_capped_by_k_when_gold_exceeds_k(self) -> None:
        # k = 2 means the ideal ranking also has only two gain positions.
        assert ndcg_at_k({"a", "b", "c", "d"}, ["a", "b"], k=2) == 1.0

    def test_earlier_hits_score_higher(self) -> None:
        gold = {"a", "b"}
        early = ndcg_at_k(gold, ["a", "x", "b"])
        late = ndcg_at_k(gold, ["x", "a", "b"])
        assert early > late

    @pytest.mark.parametrize("k, expected", [
        (1, 1.0),
        (2, 1.0 / (1.0 + 1.0 / math.log2(3))),
        (3, (1.0 + 1.0 / math.log2(4)) / (1.0 + 1.0 / math.log2(3) + 1.0 / math.log2(4))),
        (5, (1.0 + 1.0 / math.log2(4) + 1.0 / math.log2(6))
            / (1.0 + 1.0 / math.log2(3) + 1.0 / math.log2(4))),
        (10, (1.0 + 1.0 / math.log2(4) + 1.0 / math.log2(6))
             / (1.0 + 1.0 / math.log2(3) + 1.0 / math.log2(4))),
    ])
    def test_k_is_configurable(self, k: int, expected: float) -> None:
        gold = {"a", "b", "c"}
        retrieved = ["a", "x1", "b", "x2", "c"]
        assert ndcg_at_k(gold, retrieved, k=k) == pytest.approx(expected)


class TestSourceRecall:
    def test_all_sources_recovered(self) -> None:
        gold = {"doc1:1-5", "doc2:1-5"}
        retrieved = ["doc1:1-5", "doc2:1-5", "doc3:1-5"]
        assert source_recall(gold, retrieved, source_of) == 1.0

    def test_none_recovered(self) -> None:
        gold = {"doc1:1-5", "doc2:1-5"}
        assert source_recall(gold, ["doc3:1-5", "doc4:1-5"], source_of) == 0.0

    def test_partial_sources_recovered(self) -> None:
        gold = {"doc1:1-5", "doc2:1-5"}
        retrieved = ["doc1:9-12", "doc3:1-5"]
        assert source_recall(gold, retrieved, source_of) == 0.5

    def test_empty_retrieved_returns_zero(self) -> None:
        assert source_recall({"doc1:1-5"}, [], source_of) == 0.0

    def test_extra_chunks_from_one_source_do_not_cover_another(self) -> None:
        gold = {"doc1:1-5", "doc2:1-5"}
        retrieved = ["doc1:1-5", "doc1:9-12", "doc1:20-25"]
        assert source_recall(gold, retrieved, source_of) == 0.5

    def test_different_chunk_from_same_source_counts(self) -> None:
        # Source level is coarser: another chunk of the document is a hit.
        gold = {"doc1:1-5"}
        retrieved = ["doc1:99-100"]
        assert source_recall(gold, retrieved, source_of) == 1.0

    def test_source_level_is_coarser_than_chunk_level(self) -> None:
        gold = {"doc1:1-5"}
        retrieved = ["doc1:99-100"]
        assert recall_at_k(gold, retrieved) == 0.0
        assert source_recall(gold, retrieved, source_of) == 1.0

    def test_gold_chunks_of_one_source_collapse(self) -> None:
        gold = {"doc1:1-5", "doc1:9-12"}
        assert source_recall(gold, ["doc1:1-5"], source_of) == 1.0


class TestContractValidation:
    @pytest.mark.parametrize("metric", METRIC_NAMES)
    def test_empty_gold_is_rejected(self, metric: str) -> None:
        with pytest.raises(ValueError):
            apply_metric(metric, [], ["doc1:1-9"])

    @pytest.mark.parametrize("metric", METRIC_NAMES)
    def test_duplicate_retrieved_ids_are_rejected(self, metric: str) -> None:
        with pytest.raises(ValueError):
            apply_metric(metric, ["doc1:1-9"], ["doc1:1-9", "doc2:1-9", "doc1:1-9"])

    @pytest.mark.parametrize("metric", METRIC_NAMES)
    def test_non_string_ids_are_rejected(self, metric: str) -> None:
        with pytest.raises(ValueError):
            apply_metric(metric, [1], [1])

    @pytest.mark.parametrize("metric", METRIC_NAMES)
    def test_bare_string_gold_is_rejected(self, metric: str) -> None:
        with pytest.raises(ValueError):
            apply_metric(metric, "doc1:1-9", ["doc1:1-9"])

    @pytest.mark.parametrize("metric", [recall_at_k, ndcg_at_k])
    @pytest.mark.parametrize("k", [0, -1, 1.5, "5", None, True])
    def test_invalid_k_is_rejected(self, metric, k) -> None:
        with pytest.raises(ValueError):
            metric({"a"}, ["a"], k=k)

    def test_source_of_must_be_callable(self) -> None:
        with pytest.raises(ValueError):
            source_recall({"doc1:1-9"}, ["doc1:1-9"], source_of="doc1")
