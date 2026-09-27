"""Pure retrieval metrics for the M3 evaluation.

All functions here are pure: they never open SQLite, read files, call
retrieval, or depend on pytest. They accept plain ID structures and return
``float`` values without rounding.

Shared contract:
- ``retrieved`` is a ranking ordered best-first (index 0 is rank 1). Its IDs
  must be unique; duplicates raise ``ValueError``, because a repeated item
  would silently inflate recall and NDCG.
- ``gold`` is the set of relevant chunk IDs. It must not be empty: an empty
  gold marks a broken dataset entry, and every metric here would be undefined
  or meaningless, so it raises ``ValueError``. Duplicate gold entries collapse
  into one, because gold is a set by definition.
- IDs are strings; any other type raises ``ValueError``. Passing a bare string
  where a collection is expected also raises ``ValueError``.
- ``k`` must be an integer ``>= 1`` or the call raises ``ValueError``.
- Depth: only ``recall_at_k`` and ``ndcg_at_k`` truncate at ``k`` (the M3
  plan attaches ``k`` to those two metrics). ``mrr`` and ``source_recall``
  score the ranking exactly as given, so the caller controls their depth by
  choosing what ranking to pass.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence

__all__ = ["recall_at_k", "mrr", "ndcg_at_k", "source_recall"]


def recall_at_k(
    gold: Iterable[str],
    retrieved: Sequence[str],
    k: int = 5,
) -> float:
    """Fraction of gold chunks found in the first ``k`` ranks (primary metric)."""
    _validate_k(k)
    gold_ids, retrieved_ids = _prepare(gold, retrieved)
    hits = len(gold_ids & set(retrieved_ids[:k]))
    return hits / len(gold_ids)


def mrr(gold: Iterable[str], retrieved: Sequence[str]) -> float:
    """Reciprocal rank of the first gold hit; ``0.0`` when nothing matches."""
    gold_ids, retrieved_ids = _prepare(gold, retrieved)
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in gold_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    gold: Iterable[str],
    retrieved: Sequence[str],
    k: int = 5,
) -> float:
    """Binary NDCG@k: DCG over the first ``k`` ranks, normalized by the ideal
    ranking of ``min(k, len(gold))`` relevant items."""
    _validate_k(k)
    gold_ids, retrieved_ids = _prepare(gold, retrieved)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(retrieved_ids[:k], start=1)
        if chunk_id in gold_ids
    )
    ideal_positions = min(k, len(gold_ids))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_positions + 1))
    return dcg / idcg


def source_recall(
    gold: Iterable[str],
    retrieved: Sequence[str],
    source_of: Callable[[str], str],
) -> float:
    """Fraction of gold source documents present in the provided ranking.

    Secondary metric: gold and retrieved chunk IDs are collapsed to source
    documents through the injected ``source_of`` mapping, so it never reads
    the filesystem itself. It does not replace chunk-level recall.
    """
    if not callable(source_of):
        raise ValueError(f"source_of must be callable, got {source_of!r}")
    gold_ids, retrieved_ids = _prepare(gold, retrieved)
    gold_sources = {source_of(chunk_id) for chunk_id in gold_ids}
    retrieved_sources = {source_of(chunk_id) for chunk_id in retrieved_ids}
    return len(gold_sources & retrieved_sources) / len(gold_sources)


def _prepare(gold: Iterable[str], retrieved: Sequence[str]) -> tuple[set[str], list[str]]:
    gold_ids = set(_as_id_list(gold, "gold"))
    if not gold_ids:
        raise ValueError("gold must contain at least one relevant chunk ID")
    retrieved_ids = _as_id_list(retrieved, "retrieved")
    _reject_duplicates(retrieved_ids)
    return gold_ids, retrieved_ids


def _as_id_list(ids: Iterable[str], label: str) -> list[str]:
    if isinstance(ids, (str, bytes)):
        raise ValueError(f"{label} must be a collection of chunk IDs, not a string")
    items = list(ids)
    for item in items:
        if not isinstance(item, str):
            raise ValueError(f"{label} contains a non-string chunk ID: {item!r}")
    return items


def _reject_duplicates(retrieved_ids: list[str]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for chunk_id in retrieved_ids:
        if chunk_id in seen and chunk_id not in duplicates:
            duplicates.append(chunk_id)
        seen.add(chunk_id)
    if duplicates:
        raise ValueError(f"retrieved ranking repeats chunk IDs: {duplicates}")


def _validate_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int):
        raise ValueError(f"k must be an integer, got {k!r}")
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
