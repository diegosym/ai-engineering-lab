"""Unit tests for corpus discovery and reading (kba.loader)."""
from __future__ import annotations

from pathlib import Path

from kba.loader import load_corpus


def touch(root: Path, rel: str, data: bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class TestDiscovery:
    def test_sorted_and_filtered_by_suffix(self, tmp_path: Path) -> None:
        touch(tmp_path, "b.md", b"# B\nbody\n")
        touch(tmp_path, "a.txt", b"plain\n")
        touch(tmp_path, "c.MD", b"# C\nbody\n")
        touch(tmp_path, "d.pdf", b"%PDF\n")
        touch(tmp_path, "e.markdown", b"# E\nbody\n")
        report = load_corpus(tmp_path)
        names = [Path(d.source_file).name for d in report.documents]
        assert names == ["a.txt", "b.md", "c.MD"]
        skipped = [Path(p).name for p in report.skipped]
        assert skipped == ["d.pdf", "e.markdown"]

    def test_recursive_discovery(self, tmp_path: Path) -> None:
        touch(tmp_path, "sub/deeper/nested.md", b"# N\nbody\n")
        report = load_corpus(tmp_path)
        assert len(report.documents) == 1
        assert report.documents[0].source_file.endswith("nested.md")

    def test_fmt_derived_from_lowercased_suffix(self, tmp_path: Path) -> None:
        touch(tmp_path, "upper.MD", b"# U\nbody\n")
        report = load_corpus(tmp_path)
        assert report.documents[0].fmt == "md"


class TestReading:
    def test_bom_stripped_and_crlf_normalized(self, tmp_path: Path) -> None:
        touch(tmp_path, "bom.md", "﻿# Title\r\nline two\r\nline three\r\n".encode())
        doc = load_corpus(tmp_path).documents[0]
        assert doc.text.startswith("# Title")
        assert "\r" not in doc.text
        assert doc.text.split("\n")[1] == "line two"

    def test_empty_file_reported_not_loaded(self, tmp_path: Path) -> None:
        touch(tmp_path, "blank.md", b"   \n\t\n")
        report = load_corpus(tmp_path)
        assert report.documents == []
        assert len(report.empty) == 1

    def test_undecodable_file_reported(self, tmp_path: Path) -> None:
        touch(tmp_path, "bad.md", b"\xff\xfe not utf-8 \x80\x81")
        report = load_corpus(tmp_path)
        assert report.documents == []
        assert len(report.undecodable) == 1
        assert report.undecodable[0].endswith("bad.md")

    def test_valid_utf8_multibyte_preserved(self, tmp_path: Path) -> None:
        touch(tmp_path, "uni.md", "# Título — café\n".encode("utf-8"))
        doc = load_corpus(tmp_path).documents[0]
        assert "café" in doc.text
        assert "—" in doc.text
