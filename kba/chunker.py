"""Heading-aware chunking (FR2).

Design notes (approved M1 decisions):

* Markdown is split into *sections* at ATX headings (``#``..``######``),
  detected only outside fenced code blocks. Setext headings and YAML front
  matter are not supported (the corpus does not use them).
* Section content is split into atomic *blocks* (paragraph, table, list,
  quote, fenced code). Blocks are never split apart: a table or fence that
  exceeds the chunk size is emitted whole and is visible via ``char_count``.
  Only a plain paragraph may be hard-split, at a word boundary.
* Chunks never cross a section boundary. ``chunk_size`` is therefore a
  ceiling on a single section's packed body — not a budget for merging
  sections. With this corpus most sections fit in exactly one chunk.
* ``overlap`` characters from the end of the previous chunk's body are
  repeated at the start of the next chunk's body, *within the same section
  only*, so ``section`` metadata stays truthful (citations are correctness).
* Every Markdown chunk's text starts with its leaf heading line, repeated
  for each sub-chunk of a long section, so each chunk is self-describing.
* Line ranges: the first chunk of a section starts at its heading line and
  ends at its last content line; later sub-chunks span their own blocks.
  Approved caveat: for sub-chunks after the first, the repeated heading line
  and the overlap prefix physically originate earlier lines than
  ``start_line``; the range always covers the chunk's own blocks exactly.
* ``.txt`` files have no headings: one logical section, ``title`` = file
  stem, ``section`` = "", no heading line in the text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .loader import Document

DEFAULT_CHUNK_SIZE = 1200  # characters, applied to a section's packed body
DEFAULT_OVERLAP = 150      # characters, within a section only

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})")
_FENCE_CLOSE = re.compile(r"^\s*(`{3,}|~{3,})\s*$")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_TABLE = re.compile(r"^\s*\|")
_QUOTE = re.compile(r"^\s*>")
_ATOMIC = {"table", "fence", "list", "quote"}


@dataclass(frozen=True)
class Block:
    kind: str
    text: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class Section:
    heading: str | None        # raw heading line; None for .txt / leading text
    heading_line: int | None
    heads: tuple[str, ...]     # breadcrumb below the H1 (empty for preamble)
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Chunk:
    id: str
    source_file: str
    format: str
    title: str
    section: str
    chunk_index: int
    chunk_count: int
    start_line: int
    end_line: int
    char_count: int
    text: str


def parse_markdown(
    text: str, stem: str
) -> tuple[str, list[str], list[Section]]:
    """Split Markdown into sections at ATX headings (fence-aware)."""
    warnings: list[str] = []
    title: str | None = None
    h1_seen = False
    stack: list[tuple[int, str]] = []
    sections: list[Section] = []
    blocks: list[Block] = []
    cur: list[str] = []
    cur_kind: str | None = None
    cur_start = 0
    heading: str | None = None
    heading_line: int | None = None
    heads: tuple[str, ...] = ()
    fence_char = ""
    fence_len = 0

    def flush_block() -> None:
        nonlocal cur, cur_kind
        if cur:
            blocks.append(
                Block(cur_kind or "paragraph", "\n".join(cur), cur_start,
                      cur_start + len(cur) - 1)
            )
            cur = []
            cur_kind = None

    def close_section() -> None:
        nonlocal blocks
        flush_block()
        if blocks:
            sections.append(Section(heading, heading_line, heads, tuple(blocks)))
        blocks = []

    for line_no, line in enumerate(text.split("\n"), start=1):
        if fence_char:  # inside a fenced block: everything is atomic
            cur.append(line)
            m = _FENCE_CLOSE.match(line)
            if (m and m.group(1)[0] == fence_char
                    and len(m.group(1)) >= fence_len):
                flush_block()
                fence_char = ""
            continue

        m = _HEADING.match(line)
        if m:
            close_section()
            level, heading_text = len(m.group(1)), m.group(2)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading_text))
            if level == 1:
                h1_seen = True
                if title is None:
                    title = heading_text
            heads = tuple(t for _, t in stack[1:]) if h1_seen else \
                tuple(t for _, t in stack)
            heading, heading_line = line, line_no
            continue

        if not line.strip():
            flush_block()
            continue

        m = _FENCE_OPEN.match(line)
        if m:
            flush_block()
            cur, cur_kind, cur_start = [line], "fence", line_no
            fence_char, fence_len = m.group(1)[0], len(m.group(1))
            continue

        if _TABLE.match(line):
            kind = "table"
        elif _QUOTE.match(line):
            kind = "quote"
        elif _LIST.match(line):
            kind = "list"
        else:
            kind = "paragraph"

        continuation = cur_kind == "list" and kind == "paragraph"
        if cur and (kind == cur_kind or continuation):
            cur.append(line)
        else:
            flush_block()
            cur, cur_kind, cur_start = [line], kind, line_no

    close_section()

    if title is None:
        title = stem
        warnings.append(
            f"{stem}: no level-1 heading; title defaults to file name"
        )
    return title, warnings, sections


def plain_blocks(text: str) -> tuple[Block, ...]:
    """Blank-line-separated paragraphs; no Markdown interpretation (.txt)."""
    blocks: list[Block] = []
    cur: list[str] = []
    start = 0
    for line_no, line in enumerate(text.split("\n"), start=1):
        if line.strip():
            if not cur:
                start = line_no
            cur.append(line)
        elif cur:
            blocks.append(Block("paragraph", "\n".join(cur), start,
                                start + len(cur) - 1))
            cur = []
    if cur:
        blocks.append(Block("paragraph", "\n".join(cur), start,
                            start + len(cur) - 1))
    return tuple(blocks)


def overlap_prefix(body: str, overlap: int) -> str:
    """Tail of *body* (≤ *overlap* chars) starting at a word boundary."""
    if overlap <= 0 or not body:
        return ""
    if len(body) <= overlap:
        return body
    cut = body[-overlap:]
    space = cut.find(" ")
    if space != -1 and space + 1 < len(cut):
        cut = cut[space + 1:]
    return cut


def split_block(block: Block, size: int) -> list[tuple[str, int, int]]:
    """Hard-split an oversize plain paragraph at word boundaries."""
    text, pos = block.text, 0
    base = block.start_line
    pieces: list[tuple[str, int, int]] = []
    while len(text) - pos > size:
        cut = text[pos:pos + size].rfind(" ")
        if cut <= 0:
            cut = size
        chunk_text = text[pos:pos + cut]
        start = base + text.count("\n", 0, pos)
        end = base + text.count("\n", 0, pos + cut - 1)
        pieces.append((chunk_text, start, end))
        pos += cut + 1 if text[pos + cut:pos + cut + 1] == " " else cut
    pieces.append((text[pos:], base + text.count("\n", 0, pos),
                   base + text.count("\n", 0, len(text) - 1)))
    return pieces


def pack_section(
    section: Section, size: int
) -> list[tuple[str, int, int]]:
    """Pack a section's blocks into ``(body, start_line, end_line)`` pieces."""
    pieces: list[tuple[str, int, int]] = []
    current: list[Block] = []

    def packed_size(items: list[Block]) -> int:
        return sum(len(b.text) for b in items) + 2 * (len(items) - 1)

    def flush() -> None:
        nonlocal current
        if current:
            pieces.append(("\n\n".join(b.text for b in current),
                           current[0].start_line, current[-1].end_line))
            current = []

    for block in section.blocks:
        if current and packed_size(current) + 2 + len(block.text) > size:
            flush()
        if len(block.text) > size:
            if block.kind in _ATOMIC:
                pieces.append((block.text, block.start_line, block.end_line))
            else:
                pieces.extend(split_block(block, size))
        else:
            current.append(block)
    flush()
    return pieces


def chunk_document(
    doc: Document,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> tuple[list[Chunk], list[str]]:
    """Chunk one document. Returns ``(chunks, warnings)``."""
    if chunk_size < 1 or not (0 <= overlap < chunk_size):
        raise ValueError(
            "require chunk_size >= 1 and 0 <= overlap < chunk_size"
        )

    warnings: list[str] = []
    if doc.fmt == "md":
        title, warns, sections = parse_markdown(
            doc.text, Path(doc.source_file).stem
        )
        warnings.extend(warns)
    else:
        title = Path(doc.source_file).stem
        sections = [Section(None, None, (), plain_blocks(doc.text))]

    built: list[dict] = []
    for section in sections:
        pieces = pack_section(section, chunk_size)
        previous_body = ""
        for index, (body, start, end) in enumerate(pieces):
            prefix = overlap_prefix(previous_body, overlap)
            parts = []
            if section.heading:
                parts.append(section.heading)
            if prefix:
                parts.append(prefix)
            parts.append(body)
            if index == 0 and section.heading_line is not None:
                start = section.heading_line
            built.append({
                "id": f"{doc.source_file}:{start}-{end}",
                "source_file": doc.source_file,
                "format": doc.fmt,
                "title": title,
                "section": " > ".join(section.heads),
                "start_line": start,
                "end_line": end,
                "text": "\n\n".join(parts),
            })
            previous_body = body

    total = len(built)
    chunks = [
        Chunk(**entry, chunk_index=i, chunk_count=total,
              char_count=len(entry["text"]))
        for i, entry in enumerate(built)
    ]
    return chunks, warnings
