"""THROWAWAY M2 spike — lexical retrieval candidates. NOT part of kba/.

Runs the same 9 queries against 4 candidates over chunks.jsonl (65 chunks):
bm25s, SQLite FTS5, tantivy, rank_bm25 (baseline). Prints top-5 with
source_file/section/score. Qualitative inspection only — no aggregate scores.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
K = 5

QUERIES = [
    ("Q1 retry terminology", "How are retries handled?"),
    ("Q2 near-miss 15s vs 45s", "What sampling interval does the gateway use?"),
    ("Q3 near-miss 600 vs 60/min", "How many requests per minute are allowed?"),
    ("Q4 synonym/notify", "How are engineers notified when something fails at night?"),
    ("Q5 single-doc concentrated", "What hardware does the CG-200 gateway use?"),
    ("Q6 overlapping concepts", "Who do we escalate to when an incident drags on?"),
    ("Q7 lexical-friendly", "What is the exponential backoff retry schedule?"),
    ("Q8 lexical limitation", "How do employees log in to the system?"),
    ("Q9 lexical-friendly + overlap", "When does the ingestion pipeline flush queued batches?"),
]


def load_chunks() -> list[dict]:
    records = [json.loads(line) for line in (ROOT / "chunks.jsonl").read_text().splitlines() if line]
    assert len(records) == 65, len(records)
    return records


def fmt(rank: int, rec: dict, score: float) -> str:
    return (f"  {rank}. [{score:>10.4f}] {rec['source_file']} :: "
            f"{rec['section'] or '(no section)'}  #{rec['chunk_index']}")


# ---------------------------------------------------------------- bm25s
def run_bm25s(chunks, results):
    import bm25s

    corpus = [c["text"] for c in chunks]
    tok_corpus = bm25s.tokenize(corpus, stopwords="en")
    retriever = bm25s.BM25()
    retriever.index(tok_corpus)
    results["bm25s meta"] = (
        f"BM25 params: k1={retriever.k1} b={retriever.b} "
        f"(bm25s {bm25s.__version__}); persistence API: "
        f"{[m for m in ('save', 'load') if hasattr(retriever, m)]}"
    )
    for label, query in QUERIES:
        # get_scores accepts a list of string tokens; they are looked up in
        # the corpus vocabulary (a separate tokenize() call yields IDs from
        # a *different* vocabulary, which get_scores rejects)
        qtok = [t for t in query.lower().split() if t not in {"?", ","}]
        scores = retriever.get_scores(qtok)
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:K]
        results[f"bm25s | {label}"] = [
            fmt(r + 1, chunks[i], float(scores[i])) for r, i in enumerate(order)
        ]
    # also exercise the first-class top-k API for DX observation
    try:
        res, sc = retriever.retrieve(
            [[t for t in QUERIES[0][1].lower().split()]], k=K,
            show_progress=False)
        results["bm25s retrieve() API"] = (
            f"retrieve(List[List[str]]) ok; top token strings for Q1: "
            f"{list(res[0][0])[:6]}"
        )
    except Exception as exc:
        results["bm25s retrieve() API"] = f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- SQLite FTS5
def run_fts5(chunks, results):
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE VIRTUAL TABLE chunks USING fts5(
        id UNINDEXED, source_file UNINDEXED, section UNINDEXED, text)""")
    conn.executemany(
        "INSERT INTO chunks VALUES (?,?,?,?)",
        [(c["id"], c["source_file"], c["section"], c["text"]) for c in chunks],
    )
    results["fts5 meta"] = (
        "sqlite " + sqlite3.sqlite_version + "; tokenizer default (unicode61, "
        "no stemming); FTS5 bm25() returns negative values (lower = better)"
    )
    for label, query in QUERIES:
        # realistic app integration: terms are extracted and joined with AND
        terms = [t for t in query.replace("?", " ").split() if t]
        match = " AND ".join(f'"{t}"' for t in terms)
        rows = conn.execute(
            "SELECT source_file, section, bm25(chunks), rowid "
            "FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT ?",
            (match, K),
        ).fetchall()
        if not rows:
            # observe default AND behavior honestly, then show OR variant
            rows = conn.execute(
                "SELECT source_file, section, bm25(chunks), rowid "
                "FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT ?",
                (" OR ".join(f'"{t}"' for t in terms), K),
            ).fetchall()
            note = "  (AND matched nothing -> showed OR variant)"
        else:
            note = ""
        results[f"fts5 | {label}"] = [
            f"  {r+1}. [{row[2]:>10.4f}] {row[0]} :: {row[1] or '(no section)'} "
            f"(rowid {row[3]})" for r, row in enumerate(rows)
        ] + [note] if note else [
            f"  {r+1}. [{row[2]:>10.4f}] {row[0]} :: {row[1] or '(no section)'} "
            f"(rowid {row[3]})" for r, row in enumerate(rows)
        ]


# ---------------------------------------------------------------- tantivy
def run_tantivy(chunks, results):
    import tantivy

    builder = tantivy.SchemaBuilder()
    try:
        builder.add_text_field("source_file", stored=True)
        builder.add_text_field("section", stored=True)
        builder.add_text_field("text", stored=True)
    except TypeError:
        builder.add_text_field("source_file", tantivy.STORED)
        builder.add_text_field("section", tantivy.STORED)
        builder.add_text_field("text", tantivy.TEXT | tantivy.STORED)
    schema = builder.build()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        idx_dir = Path(tmp) / "idx"
        idx_dir.mkdir()  # tantivy-py requires the directory to pre-exist
        index = tantivy.Index(schema, str(idx_dir))
        writer = index.writer()
        for c in chunks:
            writer.add_document(
                tantivy.Document(
                    source_file=c["source_file"], section=c["section"], text=c["text"]
                )
            )
        writer.commit()
        index.reload()  # tantivy-py: searcher only sees committed segments after reload()
        searcher = index.searcher()
        results["tantivy meta"] = (
            f"tantivy 0.26.2 (pip wheel, cp313 x86_64); index written to a "
            "directory (persists on disk); default BM25 (documented "
            "k1=1.2 b=0.75); query parser default: disjunction (OR) across "
            "terms, default field 'text'; default tokenizer = lowercase + "
            "alphanumeric split, no stemming; searcher.num_docs="
            f"{searcher.num_docs}"
        )
        for label, query in QUERIES:
            q = index.parse_query(query, ["text"])  # 0.26 API: default OR (conjunction_by_default=False)
            hits = searcher.search(q, K)
            rows = []
            raw_hits = hits if isinstance(hits, list) else getattr(hits, "hits", hits)
            for r, hit in enumerate(raw_hits):
                score, addr = (hit[0], hit[1]) if not hasattr(hit, "doc_address") else (hit.score, hit.doc_address)
                doc = searcher.doc(addr)
                rows.append(
                    f"  {r+1}. [{score:>10.4f}] {doc['source_file']} :: "
                    f"{doc['section'] or '(no section)'}"
                )
            results[f"tantivy | {label}"] = rows
        results["tantivy persistence"] = (
            f"index files written under tmp dir; searcher sees "
            f"{searcher.num_docs} docs"
        )


# ---------------------------------------------------------------- rank_bm25
def run_rank_bm25(chunks, results):
    from rank_bm25 import BM25Okapi

    corpus = [c["text"].lower().split() for c in chunks]
    bm25 = BM25Okapi(corpus)
    results["rank_bm25 meta"] = (
        "BM25Okapi (k1=1.5, b=0.75 per BM25Okapi defaults); tokenization = "
        "plain str.split(); no persistence API (in-memory only)"
    )
    for label, query in QUERIES:
        scores = bm25.get_scores(query.lower().split())
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:K]
        results[f"rank_bm25 | {label}"] = [
            fmt(r + 1, chunks[i], float(scores[i])) for r, i in enumerate(order)
        ]


def main() -> None:
    chunks = load_chunks()
    results: dict[str, object] = {}
    runners = [("bm25s", run_bm25s), ("fts5", run_fts5),
               ("tantivy", run_tantivy), ("rank_bm25", run_rank_bm25)]
    for name, fn in runners:
        try:
            fn(chunks, results)
        except Exception as exc:  # spike must record failures, not die
            results[f"{name} ERROR"] = f"{type(exc).__name__}: {exc}"

    out = []
    for label, value in results.items():
        out.append(f"=== {label} ===")
        if isinstance(value, list):
            out.extend(str(v) for v in value if str(v))
        else:
            out.append(str(value))
        out.append("")
    text = "\n".join(out)
    print(text)
    (Path(__file__).parent / "raw-results.txt").write_text(text)


if __name__ == "__main__":
    sys.exit(main())
