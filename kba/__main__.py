"""Command-line entry point: ``ingest`` (M1), ``index``/``search`` (M2).

Exit codes:
  0 — success (including a search that legitimately found no results)
  1 — runtime failure (e.g. a corpus file is not valid UTF-8, engine error)
  2 — usage/configuration error (missing corpus dir, bad params, missing index)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .chunker import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP, chunk_document
from .indexer import DEFAULT_DB_PATH, IndexBuildError, build_index, load_records
from .loader import load_corpus
from .retrieval import (
    DEFAULT_K,
    IndexNotBuiltError,
    RetrievalError,
    retrieve,
    tokenize_query,
)
from .writer import chunk_to_record, write_jsonl

#: Deterministic CLI truncation: normal `search` output prints at most this
#: many characters of chunk text; `--full` prints the complete text.
_PREVIEW_CHARS = 400


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kba",
        description="Engineering Knowledge Assistant (M1: ingestion).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest = subparsers.add_parser(
        "ingest", help="chunk the corpus into chunks.jsonl"
    )
    ingest.add_argument("--corpus", default="docs/corpus",
                        help="corpus directory (default: docs/corpus)")
    ingest.add_argument("--out", default="chunks.jsonl",
                        help="output JSONL path (default: chunks.jsonl)")
    ingest.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"chunk size ceiling in characters "
                             f"(default: {DEFAULT_CHUNK_SIZE})")
    ingest.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP,
                        help=f"overlap characters within a section "
                             f"(default: {DEFAULT_OVERLAP})")
    ingest.add_argument("--verbose", action="store_true",
                        help="print per-file chunk counts")
    index = subparsers.add_parser(
        "index", help="build the derived FTS5 database from chunks.jsonl"
    )
    index.add_argument("--chunks", default="chunks.jsonl",
                       help="canonical chunks JSONL path (default: chunks.jsonl)")
    index.add_argument("--db", default=DEFAULT_DB_PATH,
                       help=f"output FTS5 database path (default: {DEFAULT_DB_PATH})")
    index.add_argument("--verbose", action="store_true",
                       help="print per-source chunk counts")
    search = subparsers.add_parser(
        "search", help="search the FTS5 index (retrieve(query, k))"
    )
    search.add_argument("query", help="natural-language query")
    search.add_argument("--k", type=int, default=DEFAULT_K,
                        help=f"maximum number of results (default: {DEFAULT_K})")
    search.add_argument("--db", default=DEFAULT_DB_PATH,
                        help=f"FTS5 database path (default: {DEFAULT_DB_PATH})")
    search.add_argument("--full", action="store_true",
                        help="print complete chunk text "
                             f"(default: first {_PREVIEW_CHARS} chars)")
    search.add_argument("--verbose", action="store_true",
                        help="print retrieval-policy info to stderr")
    return parser


def cmd_ingest(args: argparse.Namespace) -> int:
    if args.chunk_size < 1 or not (0 <= args.overlap < args.chunk_size):
        print("error: require chunk-size >= 1 and 0 <= overlap < chunk-size",
              file=sys.stderr)
        return 2
    corpus = Path(args.corpus)
    if not corpus.is_dir():
        print(f"error: corpus directory not found: {corpus.resolve()}",
              file=sys.stderr)
        return 2

    report = load_corpus(corpus)
    for path in report.skipped:
        print(f"warning: skipping unsupported file: {path}", file=sys.stderr)
    for path in report.empty:
        print(f"warning: skipping empty file: {path}", file=sys.stderr)
    if report.undecodable:
        for path in report.undecodable:
            print(f"error: not valid UTF-8: {path}", file=sys.stderr)
        print("error: aborting ingestion; fix the files above",
              file=sys.stderr)
        return 1

    records = []
    per_file: list[tuple[str, int]] = []
    warnings: list[str] = []
    for doc in report.documents:
        chunks, warns = chunk_document(doc, args.chunk_size, args.overlap)
        warnings.extend(warns)
        per_file.append((doc.source_file, len(chunks)))
        records.extend(chunk_to_record(chunk) for chunk in chunks)
    for message in warnings:
        print(f"warning: {message}", file=sys.stderr)

    out = Path(args.out)
    write_jsonl(records, out)
    if args.verbose:
        for source, count in per_file:
            print(f"  {count:>3} chunks  {source}")
    print(f"ingested {len(report.documents)} file(s) -> "
          f"{len(records)} chunk(s) -> {out}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """Build/rebuild the derived FTS5 database from canonical chunks.jsonl."""
    chunks = Path(args.chunks)
    if not chunks.is_file():
        print(f"error: chunks file not found: {chunks.resolve()}",
              file=sys.stderr)
        return 2

    try:
        records = load_records(chunks)
    except FileNotFoundError:
        print(f"error: chunks file not found: {chunks.resolve()}",
              file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: cannot parse {chunks}: {exc}", file=sys.stderr)
        return 1

    db = Path(args.db)
    try:
        stats = build_index(records, db)
    except (IndexBuildError, ValueError) as exc:
        print(f"error: failed to build index: {exc}", file=sys.stderr)
        return 1

    if args.verbose:
        per_source: dict[str, int] = {}
        for record in records:
            source = record["source_file"]
            per_source[source] = per_source.get(source, 0) + 1
        for source in sorted(per_source):
            print(f"  {per_source[source]:>3} chunks  {source}")
    print(f"indexed {stats.row_count} chunk(s) -> {stats.db_path}")
    return 0


def _preview(text: str) -> str:
    """Deterministic CLI truncation: the first _PREVIEW_CHARS characters."""
    if len(text) <= _PREVIEW_CHARS:
        return text
    return (f"{text[:_PREVIEW_CHARS]}… "
            f"[{len(text)} chars total; use --full]")


def cmd_search(args: argparse.Namespace) -> int:
    """Thin adapter over retrieve(query, k) — no SQL or policy logic here."""
    db = Path(args.db)
    try:
        results = retrieve(args.query, args.k, db_path=db)
    except IndexNotBuiltError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: invalid search: {exc}", file=sys.stderr)
        return 2
    except RetrievalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.verbose:
        tokens = tokenize_query(args.query)
        print(f"policy: disjunction (OR) over {len(tokens)} token(s): "
              f"{', '.join(tokens)}", file=sys.stderr)
        print("ranking: FTS5 bm25, score = -bm25 (higher = better); "
              f"k = {args.k}", file=sys.stderr)
        print(f"index: {db.resolve()}", file=sys.stderr)

    if not results:
        print(f"no results for: {args.query}")
        return 0

    print(f"{len(results)} result(s) for: {args.query}")
    print()
    for rank, result in enumerate(results, start=1):
        section = result.section or "(preamble)"
        print(f"{rank}. [{result.score:8.4f}] "
              f"{result.source_file} :: {section}")
        print(f"   id: {result.id}")
        body = result.text if args.full else _preview(result.text)
        for line in body.splitlines() or [""]:
            print(f"   {line}")
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "ingest":
        return cmd_ingest(args)
    if args.command == "index":
        return cmd_index(args)
    if args.command == "search":
        return cmd_search(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
