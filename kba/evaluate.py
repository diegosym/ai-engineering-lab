"""M3 evaluation runner: golden dataset -> retriever -> metrics -> records.

Separation of responsibilities (each symbol owns exactly one job):

- ``load_golden_dataset``    — read and validate the golden JSONL (the only
  dataset I/O; it does not check labels against chunks.jsonl, which
  ``tests/test_golden_dataset.py`` owns).
- ``temporary_fts5_retriever`` — rebuild a fresh FTS5 index from canonical
  ``chunks.jsonl`` inside a temp directory that is removed on exit, so
  evaluation never depends on a ``chunks.db`` in the working tree
  (M3 baseline 1).
- ``canonical_order_retriever`` — the first *k* chunks in canonical
  ``chunks.jsonl`` order: no lexical ranking, no ``retrieve()`` call
  (M3 baseline 2).
- ``extract_ids``            — ranked ``SearchResult`` objects -> ordered
  chunk IDs (the retrieval contract, not a copy of retrieval logic).
- ``run_evaluation``         — orchestrate: call the retriever per query,
  run the pure ``kba.metrics`` functions, build serializable records.
- ``summarize``              — macro-average aggregation over queries.
- ``build_results_document`` — assemble the deterministic
  ``m3-baseline-results.json`` payload from one run per baseline.

Retriever contract (injected, never duplicated): the real
``kba.retrieval.retrieve(query, k, *, db_path)`` wrapped as
``retriever(query, k) -> Sequence[SearchResult]``. Tests inject fakes; the
M3 baselines (FTS5, canonical ``chunks.jsonl`` order, later random) all plug
into the same slot, so one metrics path serves every ranking.

Determinism: same golden dataset + same ``chunks.jsonl`` + same retriever +
same ``k`` => byte-equivalent ``EvaluationRun.to_dict()`` output. No
randomness, no network, no LLM, no timestamps, and no filesystem paths in
the records.

CLI: deliberately not implemented in this stage — a command-line entry
point would mix I/O, formatting, and orchestration with the runner, and the
result format is owned by the baseline/report stage.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .indexer import build_index, load_records
from .metrics import mrr, ndcg_at_k, recall_at_k, source_recall
from .retrieval import DEFAULT_K, SearchResult, retrieve

#: Canonical inputs, following the CLI's relative-path convention.
DEFAULT_CHUNKS_PATH = Path("chunks.jsonl")
DEFAULT_GOLDEN_PATH = Path("docs/eval/golden-queries.jsonl")

#: Injected retriever: the real ``retrieve`` bound to a database, or a fake.
Retriever = Callable[[str, int], Sequence[SearchResult]]

#: Chunk identity convention owned by M1: ``<source_file>:<start>-<end>``.
_CHUNK_ID_RE = re.compile(r"^(?P<source>.+):\d+-\d+$")

#: The dataset fields the runner consumes (full schema: docs/eval/README.md).
_REQUIRED_FIELDS = ("id", "query", "taxonomy", "relevant_chunk_ids")


@dataclass(frozen=True)
class GoldenQuery:
    """One entry of the golden dataset, as consumed by the runner."""

    query_id: str
    query: str
    taxonomy: str
    relevant_chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class QueryEvaluation:
    """Serializable per-query evaluation record.

    ``recall`` and ``ndcg`` are Recall@k and NDCG@k; every record carries
    ``k`` (5 for the M3 baseline) so the numbers are self-describing.
    """

    query_id: str
    query: str
    taxonomy: str
    relevant_chunk_ids: tuple[str, ...]
    retrieved_chunk_ids: tuple[str, ...]
    k: int
    recall: float
    mrr: float
    ndcg: float
    source_recall: float

    def to_dict(self) -> dict:
        return {
            "query_id": self.query_id,
            "query": self.query,
            "taxonomy": self.taxonomy,
            "relevant_chunk_ids": list(self.relevant_chunk_ids),
            "retrieved_chunk_ids": list(self.retrieved_chunk_ids),
            "k": self.k,
            "recall": self.recall,
            "mrr": self.mrr,
            "ndcg": self.ndcg,
            "source_recall": self.source_recall,
        }


@dataclass(frozen=True)
class EvaluationSummary:
    """Macro-average over queries (each query weighs the same)."""

    query_count: int
    recall: float
    mrr: float
    ndcg: float
    source_recall: float

    def to_dict(self) -> dict:
        return {
            "query_count": self.query_count,
            "recall": self.recall,
            "mrr": self.mrr,
            "ndcg": self.ndcg,
            "source_recall": self.source_recall,
        }


@dataclass(frozen=True)
class EvaluationRun:
    """Complete evaluation output: one record per query plus its summary."""

    k: int
    queries: tuple[QueryEvaluation, ...]
    summary: EvaluationSummary

    def to_dict(self) -> dict:
        return {
            "k": self.k,
            "queries": [record.to_dict() for record in self.queries],
            "summary": self.summary.to_dict(),
        }


def load_golden_dataset(path: Path = DEFAULT_GOLDEN_PATH) -> list[GoldenQuery]:
    """Read and validate the golden dataset JSONL.

    Raises:
        FileNotFoundError: *path* does not exist.
        ValueError: invalid JSON line, missing/mistyped required field,
            duplicate query id, or a dataset with no queries at all.
    """
    text = Path(path).read_text(encoding="utf-8")
    entries: list[GoldenQuery] = []
    seen_ids: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        record = _parse_line(line, lineno)
        entry = _to_golden_query(record, lineno)
        if entry.query_id in seen_ids:
            raise ValueError(f"line {lineno}: duplicate query id {entry.query_id!r}")
        seen_ids.add(entry.query_id)
        entries.append(entry)
    if not entries:
        raise ValueError(f"golden dataset has no queries: {path}")
    return entries


def source_of_chunk_id(chunk_id: str) -> str:
    """Source document of a chunk ID (``<source_file>:<start>-<end>``).

    Deriving the source from the ID keeps the metric layer free of
    filesystem access; the mapping is validated against ``source_file`` for
    every canonical chunk.

    Raises:
        ValueError: *chunk_id* does not follow the M1 chunk-ID convention.
    """
    if not isinstance(chunk_id, str):
        raise ValueError(f"chunk id must be a str, got {type(chunk_id).__name__}")
    match = _CHUNK_ID_RE.match(chunk_id)
    if not match:
        raise ValueError(
            f"not a valid chunk id (expected '<source>:<start>-<end>'): {chunk_id!r}"
        )
    return match.group("source")


def extract_ids(results: Sequence[SearchResult]) -> list[str]:
    """Ordered chunk IDs from a ranked result list (order preserved)."""
    return [result.id for result in results]


def run_evaluation(
    dataset: Sequence[GoldenQuery],
    retriever: Retriever,
    *,
    k: int = DEFAULT_K,
) -> EvaluationRun:
    """Evaluate *retriever* over every query of *dataset*.

    One record per query, in dataset order; metrics come from the pure
    ``kba.metrics`` functions with the same *k* passed to the retriever
    (``mrr`` and source recall take the ranking as returned). Retriever
    failures propagate untouched — a partial run is never returned.

    Raises:
        ValueError: empty *dataset* or invalid *k* (checked before the
            retriever is called).
    """
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError(f"k must be an integer >= 1, got {k!r}")
    if not dataset:
        raise ValueError("dataset is empty; nothing to evaluate")

    records: list[QueryEvaluation] = []
    for entry in dataset:
        retrieved_ids = extract_ids(retriever(entry.query, k))
        gold = entry.relevant_chunk_ids
        records.append(
            QueryEvaluation(
                query_id=entry.query_id,
                query=entry.query,
                taxonomy=entry.taxonomy,
                relevant_chunk_ids=tuple(gold),
                retrieved_chunk_ids=tuple(retrieved_ids),
                k=k,
                recall=recall_at_k(gold, retrieved_ids, k=k),
                mrr=mrr(gold, retrieved_ids),
                ndcg=ndcg_at_k(gold, retrieved_ids, k=k),
                source_recall=source_recall(gold, retrieved_ids, source_of_chunk_id),
            )
        )
    return EvaluationRun(k=k, queries=tuple(records), summary=summarize(records))


def summarize(queries: Sequence[QueryEvaluation]) -> EvaluationSummary:
    """Macro-average the per-query metrics (each query weighs the same)."""
    if not queries:
        raise ValueError("cannot summarize zero queries")
    count = len(queries)
    return EvaluationSummary(
        query_count=count,
        recall=sum(record.recall for record in queries) / count,
        mrr=sum(record.mrr for record in queries) / count,
        ndcg=sum(record.ndcg for record in queries) / count,
        source_recall=sum(record.source_recall for record in queries) / count,
    )


def build_results_document(
    runs: Mapping[str, EvaluationRun],
    *,
    dataset_path: Path = DEFAULT_GOLDEN_PATH,
    corpus_path: Path = DEFAULT_CHUNKS_PATH,
) -> dict:
    """Assemble the deterministic ``m3-baseline-results.json`` payload.

    *runs* maps baseline name -> run, in the order the baselines should be
    listed. All runs must share one ``k`` and the same queries in the same
    order (both checked), so the document cannot silently mix evaluations.

    The only I/O is reading the two input files for their SHA-256
    fingerprints and record counts. There are no timestamps, absolute
    paths, or machine-dependent values: ``json.dumps(document,
    sort_keys=True, indent=2)`` yields byte-identical JSON for the same
    inputs on any machine.
    """
    if not runs:
        raise ValueError("no baseline runs to report")
    entries = list(runs.values())
    ks = {run.k for run in entries}
    if len(ks) != 1:
        raise ValueError(f"all baselines must share a single k, got {sorted(ks)}")
    query_orders = {
        tuple(record.query_id for record in run.queries) for run in entries
    }
    if len(query_orders) != 1:
        raise ValueError(
            "all baselines must evaluate the same queries in the same order"
        )
    k = entries[0].k
    return {
        "schema_version": 1,
        "k": k,
        "metrics": {
            "chunk_level": [f"recall@{k}", "mrr", f"ndcg@{k}"],
            "source_level": ["source_recall"],
            "aggregation": "macro-mean over queries",
        },
        "dataset": {
            "path": Path(dataset_path).as_posix(),
            "sha256": _sha256(dataset_path),
            "query_count": len(next(iter(query_orders))),
        },
        "corpus": {
            "path": Path(corpus_path).as_posix(),
            "sha256": _sha256(corpus_path),
            "chunk_count": _count_records(corpus_path),
        },
        "baselines": list(runs),
        "results": {
            name: {
                "summary": run.summary.to_dict(),
                "queries": [record.to_dict() for record in run.queries],
            }
            for name, run in runs.items()
        },
    }


@contextmanager
def temporary_fts5_retriever(
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
) -> Iterator[Retriever]:
    """Yield a ``retrieve(query, k)`` retriever backed by a throwaway index.

    The index is rebuilt from *chunks_path* with the existing
    ``load_records``/``build_index`` pair on every entry, in canonical
    ``chunks.jsonl`` order (deterministic rowids), and lives in a temp
    directory that is deleted when the context exits — evaluation never
    reads or writes a ``chunks.db`` in the working tree. A retriever used
    after the exit raises ``IndexNotBuiltError`` like any missing index.
    """
    records = load_records(Path(chunks_path))
    with tempfile.TemporaryDirectory(prefix="kba-eval-") as tmp:
        db_path = Path(tmp) / "chunks.db"
        build_index(records, db_path)

        def retriever(query: str, k: int) -> list[SearchResult]:
            return retrieve(query, k, db_path=db_path)

        yield retriever


def canonical_order_retriever(
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
) -> Retriever:
    """Baseline retriever: the first *k* chunks in canonical file order.

    The second mandatory M3 baseline answers with document position instead
    of relevance: it reads *chunks_path* once with ``load_records``, keeps
    the canonical ``chunks.jsonl`` order exactly (no sorting, no lexical
    ranking, no randomness, and no ``retrieve()`` call), and returns the
    first *k* chunks with no padding. It satisfies the same
    ``retriever(query, k)`` contract as FTS5, so the runner and the metric
    functions are shared unchanged. ``SearchResult.score`` is always ``0.0``
    — this baseline claims no relevance ordering beyond canonical position;
    *query* is intentionally ignored.
    """
    corpus = tuple(
        SearchResult(
            id=record["id"],
            source_file=record["source_file"],
            section=record["section"],
            text=record["text"],
            score=0.0,
        )
        for record in load_records(Path(chunks_path))
    )

    def retriever(query: str, k: int) -> list[SearchResult]:
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError(f"k must be an integer >= 1, got {k!r}")
        return list(corpus[:k])

    return retriever


def _sha256(path: Path) -> str:
    """Content fingerprint of an input file (machine-independent)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _count_records(path: Path) -> int:
    """Number of non-empty JSONL records in *path*."""
    text = Path(path).read_text(encoding="utf-8")
    return sum(1 for line in text.splitlines() if line.strip())


def _parse_line(line: str, lineno: int) -> dict:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"line {lineno}: invalid JSON: {exc}") from exc
    if not isinstance(record, dict):
        raise ValueError(f"line {lineno}: expected a JSON object")
    missing = [field for field in _REQUIRED_FIELDS if field not in record]
    if missing:
        raise ValueError(f"line {lineno}: missing field(s): {', '.join(missing)}")
    return record


def _to_golden_query(record: dict, lineno: int) -> GoldenQuery:
    query_id = record["id"]
    query = record["query"]
    taxonomy = record["taxonomy"]
    gold = record["relevant_chunk_ids"]
    if not isinstance(query_id, str) or not query_id:
        raise ValueError(f"line {lineno}: 'id' must be a non-empty string")
    if not isinstance(query, str) or not query.strip():
        raise ValueError(f"line {lineno}: 'query' must be a non-empty string")
    if not isinstance(taxonomy, str) or not taxonomy:
        raise ValueError(f"line {lineno}: 'taxonomy' must be a non-empty string")
    if not isinstance(gold, list) or not gold:
        raise ValueError(
            f"line {lineno}: 'relevant_chunk_ids' must be a non-empty list"
        )
    if not all(isinstance(chunk_id, str) and chunk_id for chunk_id in gold):
        raise ValueError(
            f"line {lineno}: 'relevant_chunk_ids' must hold non-empty strings"
        )
    return GoldenQuery(
        query_id=query_id,
        query=query,
        taxonomy=taxonomy,
        relevant_chunk_ids=tuple(gold),
    )
