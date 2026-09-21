"""Corpus discovery and document reading (FR1).

Reads ``.md`` and ``.txt`` files from a configured directory as UTF-8 text.
A leading BOM is stripped and CRLF/CR newlines are normalized to ``\\n`` so
line numbers are stable across platforms and editors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_SUFFIXES = {".md", ".txt"}


@dataclass(frozen=True)
class Document:
    path: Path
    source_file: str  # POSIX path relative to the working directory
    fmt: str          # "md" | "txt"
    text: str


@dataclass
class LoadReport:
    documents: list[Document] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)      # unsupported suffix
    empty: list[str] = field(default_factory=list)        # whitespace-only
    undecodable: list[str] = field(default_factory=list)  # not valid UTF-8


def discover(corpus_dir: Path) -> list[Path]:
    """Every file under *corpus_dir* (recursive), sorted for determinism."""
    return sorted(p for p in corpus_dir.rglob("*") if p.is_file())


def rel_source(path: Path) -> str:
    """POSIX path relative to the working directory when possible."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def load_corpus(corpus_dir: Path) -> LoadReport:
    """Read every supported file in *corpus_dir* into a :class:`Document`."""
    report = LoadReport()
    for path in discover(corpus_dir):
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            report.skipped.append(str(path))
            continue
        try:
            text = path.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError:
            report.undecodable.append(str(path))
            continue
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            report.empty.append(str(path))
            continue
        report.documents.append(
            Document(
                path=path,
                source_file=rel_source(path),
                fmt=suffix.lstrip("."),
                text=text,
            )
        )
    return report
