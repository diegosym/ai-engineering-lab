"""Command-line entry point: ``python -m kba ingest`` (M1).

``kba search`` is added in M2. Exit codes:
  0 — success
  1 — runtime failure (e.g. a corpus file is not valid UTF-8)
  2 — usage/configuration error (missing corpus dir, invalid parameters)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .chunker import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP, chunk_document
from .loader import load_corpus
from .writer import chunk_to_record, write_jsonl


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "ingest":
        return cmd_ingest(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
