"""JSONL persistence for chunks (FR3).

Writes one JSON object per line, ``ensure_ascii=False``, UTF-8, trailing
newline. The file is written to a temporary sibling and atomically renamed
(``Path.replace``) so readers never observe a partial ``chunks.jsonl``.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .chunker import Chunk


def chunk_to_record(chunk: Chunk) -> dict[str, Any]:
    """Flatten a chunk into its JSONL record (schema order preserved)."""
    return {
        "id": chunk.id,
        "source_file": chunk.source_file,
        "format": chunk.format,
        "title": chunk.title,
        "section": chunk.section,
        "chunk_index": chunk.chunk_index,
        "chunk_count": chunk.chunk_count,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "char_count": chunk.char_count,
        "text": chunk.text,
    }


def write_jsonl(records: Sequence[dict[str, Any]], out_path: Path) -> None:
    """Atomically write *records* as JSON Lines to *out_path*."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(out_path)
