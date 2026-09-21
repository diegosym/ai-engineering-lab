"""Unit tests for corpus discovery and reading (kba.loader)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kba.loader import load_corpus


class LoaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def touch(self, rel: str, data: bytes) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path


class DiscoveryTests(LoaderTestCase):
    def test_sorted_and_filtered_by_suffix(self) -> None:
        self.touch("b.md", b"# B\nbody\n")
        self.touch("a.txt", b"plain\n")
        self.touch("c.MD", b"# C\nbody\n")
        self.touch("d.pdf", b"%PDF\n")
        self.touch("e.markdown", b"# E\nbody\n")
        report = load_corpus(self.root)
        names = [Path(d.source_file).name for d in report.documents]
        self.assertEqual(names, ["a.txt", "b.md", "c.MD"])
        skipped = [Path(p).name for p in report.skipped]
        self.assertEqual(skipped, ["d.pdf", "e.markdown"])

    def test_recursive_discovery(self) -> None:
        self.touch("sub/deeper/nested.md", b"# N\nbody\n")
        report = load_corpus(self.root)
        self.assertEqual(len(report.documents), 1)
        self.assertTrue(report.documents[0].source_file.endswith("nested.md"))

    def test_fmt_derived_from_lowercased_suffix(self) -> None:
        self.touch("upper.MD", b"# U\nbody\n")
        report = load_corpus(self.root)
        self.assertEqual(report.documents[0].fmt, "md")


class ReadingTests(LoaderTestCase):
    def test_bom_stripped_and_crlf_normalized(self) -> None:
        self.touch("bom.md", "﻿# Title\r\nline two\r\nline three\r\n".encode())
        doc = load_corpus(self.root).documents[0]
        self.assertTrue(doc.text.startswith("# Title"))
        self.assertNotIn("\r", doc.text)
        self.assertEqual(doc.text.split("\n")[1], "line two")

    def test_empty_file_reported_not_loaded(self) -> None:
        self.touch("blank.md", b"   \n\t\n")
        report = load_corpus(self.root)
        self.assertEqual(report.documents, [])
        self.assertEqual(len(report.empty), 1)

    def test_undecodable_file_reported(self) -> None:
        self.touch("bad.md", b"\xff\xfe not utf-8 \x80\x81")
        report = load_corpus(self.root)
        self.assertEqual(report.documents, [])
        self.assertEqual(len(report.undecodable), 1)
        self.assertTrue(report.undecodable[0].endswith("bad.md"))

    def test_valid_utf8_multibyte_preserved(self) -> None:
        self.touch("uni.md", "# Título — café\n".encode("utf-8"))
        doc = load_corpus(self.root).documents[0]
        self.assertIn("café", doc.text)
        self.assertIn("—", doc.text)


if __name__ == "__main__":
    unittest.main()
