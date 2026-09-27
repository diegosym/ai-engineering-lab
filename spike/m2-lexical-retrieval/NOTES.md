# M2 Spike Notes — Lexical Retrieval Candidates

**Status:** THROWAWAY spike evidence for ADR-001. Not a benchmark, not a ranking.
**Date:** 2026-09-24 · **Method:** 9 queries × 4 candidates over the existing 65 chunks, k=5.
**Raw evidence:** `raw-results.txt` · **Method script:** `run_spike.py` (single file, outside `kba/`).

**How to read this document:**
- *(observed)* = produced by running code in this spike.
- *(doc)* = from library documentation, not verified by running code here.
- *(interpretation)* = our reading of the evidence.
- **Limitations** are collected in section J.

---

## A. Environment findings

*(observed)*
- Project env: conda `ai-engineering`, Python **3.13.5**, x86_64 (Mac Intel), macOS 14.6.1.
- Env was empty except pip/setuptools/wheel.
- SQLite **3.45.3** available through stdlib `sqlite3`; `CREATE VIRTUAL TABLE ... USING fts5` works.
- Default shell `python` is anaconda base (3.7.3) — all spike commands ran via `conda run -n ai-engineering`.

## B. Installation findings

*(observed)*

| Candidate | Gate result | Packages installed into `ai-engineering` |
|---|---|---|
| bm25s | PASS — wheel installs cleanly | `bm25s 0.3.11` (+ `numpy 2.5.3`) |
| SQLite FTS5 | PASS — stdlib, nothing to install | none |
| Tantivy | **PASS** — `tantivy 0.26.2` wheel resolved & installed for cp313/macOS x86_64, no compilation | `tantivy 0.26.2` |
| rank_bm25 | PASS (baseline only) | `rank-bm25 0.2.2` (shares numpy) |

- `pyproject.toml` was **not** modified.
- Tantivy install was trivial → it stays in the evaluation instead of being demoted to "documented only". Runtime DX issues (not install issues) are noted in section C.

## C. Candidate-by-candidate technology dossier

### C1. bm25s

- **Problem it solves:** fast BM25 ranking over a document collection without external infra.
- **Abstraction:** `BM25` object — `.index(tokenized_corpus)`, `.get_scores(query_tokens)`, `.retrieve()`; the library owns scoring math (tf-idf, k1/b normalization).
- **Document representation:** *(observed)* plain strings, tokenized by `bm25s.tokenize()` into a `Tokenized` object with its own vocabulary (IDs per call).
- **Indexing:** *(observed)* in-memory sparse index built by `.index()`; *(doc)* `save()`/`load()` exist for persistence (attributes observed on the object; round-trip not exercised in this spike).
- **Tokenization/config:** *(observed)* `tokenize(text, stopwords="en")`; important parameters `k1=1.5`, `b=0.75` (read off the object). *(doc)* stemming and alternative tokenizers are available.
- **Ranking:** *(observed)* BM25 scores, higher = better, 0.0 for documents with no term overlap.
- **Top-k:** *(observed)* no native top-k on `get_scores()` — we sorted manually; `.retrieve()` exists but expects pre-tokenized queries from the *same* vocabulary; passing raw strings or foreign token IDs raises, and its return shape varied during the spike (`TypeError: 'numpy.int64' object is not iterable` at one point).
- **Persistence:** *(doc)* save/load to disk; *(interpretation)* index would be a derived artifact rebuilt from `chunks.jsonl`.
- **Determinism:** *(interpretation)* deterministic for identical corpus/query/tokenizer; no randomness observed.
- **What our app still controls:** corpus construction, chunk metadata (IDs map to `chunks.jsonl`), tokenizer choice, k1/b, k, score→result mapping.
- **Complexity it removes:** scoring math, index data structures.
- **Complexity it introduces:** tokenization/vocabulary sync between corpus and query; a separate index artifact to manage.
- **Testing/debugging:** easy — pure Python/numpy, scores inspectable; DX sharp edges around `retrieve()`/tokenized queries (*observed*).
- **Limitations:** lexical only; no analyzers/facets/phrase queries out of the box; small project, less industry footprint than SQLite/tantivy.
- **When to use:** pure-Python BM25 in-process ranking when you want library-managed scoring without a storage engine.
- **When not to use:** when you need full-text-search features (phrase queries, highlighting, analyzers) or SQL integration.
- **Production-scale alternative:** a search engine (Tantivy/Elasticsearch/OpenSearch) or DB FTS.

### C2. SQLite FTS5 (stdlib `sqlite3`)

- **Problem it solves:** full-text search inside an embedded, ubiquitous SQL database.
- **Abstraction:** SQL over a virtual table — `CREATE VIRTUAL TABLE ... USING fts5(...)`, `MATCH`, `bm25()`, `ORDER BY ... LIMIT k`.
- **Document representation:** *(observed)* rows; we stored `id, source_file, section, text` with the first three `UNINDEXED`.
- **Indexing:** *(observed)* rows written with plain `INSERT`; index maintained automatically by SQLite.
- **Tokenization/config:** *(observed)* default tokenizer `unicode61` — no stemming, no stopwords; *(doc)* `porter unicode61` stemming, `remove_diacritics`, custom tokenizers, and `bm25(table, w1, ...)` column weights are configurable.
- **Ranking:** *(observed)* `bm25(chunks)` returns **negative** values; lower = better, so ordering is `ORDER BY bm25(chunks) LIMIT k` (ascending).
- **Top-k:** *(observed)* native via `LIMIT`.
- **Critical query-semantics finding:** *(observed)* FTS5's MATCH with space-joined terms defaults to **AND** — *every one of the 9 natural-language queries returned zero rows*. The application must transform queries (we re-ran with `OR`-joined terms and got results). This is an integration decision the app owns: query parsing/operator choice (AND/OR/NEAR/phrase).
- **Persistence:** *(observed)* real SQL database file (we used `:memory:` for speed); survives processes; single canonical artifact possible.
- **Determinism:** *(interpretation)* deterministic given identical DB content and query strings.
- **What our app still controls:** schema (metadata columns), query parsing/operator choice, k, mapping rowid→chunk metadata, weights in `bm25()`.
- **Complexity it removes:** indexing, score computation, persistence, and it *also* gives us SQL for free (filters by `source_file`, joins, pagination).
- **Complexity it introduces:** query-string construction (SQL/FTS injection concerns → parameterize), score sign convention, AND-default semantics, tokenizer limits (English-only stemming option).
- **Testing/debugging:** excellent — SQL is inspectable; empty-result AND behavior was itself a debugging signal.
- **Limitations:** English-centric analyzers, no BM25 tuning beyond column weights, SQLite ships one FTS config per build (though FTS5 confirmed present here).
- **When to use:** embedded, local-first, SQL-friendly apps — especially when lexical retrieval and structured metadata queries go together.
- **When not to use:** when you need distributed search, heavy analyzers, or relevance features beyond BM25.
- **Production-scale alternative:** PostgreSQL FTS (same SQL mental model, server) or a dedicated search engine.

### C3. Tantivy (`tantivy-py` 0.26.2)

- **Problem it solves:** embedded, Lucene-class full-text search engine as a library.
- **Abstraction:** schema → writer → index directory → searcher; query language, analyzers, and BM25 are engine-owned.
- **Document representation:** *(observed)* `tantivy.Document(field=value, ...)`; stored fields read back as **lists** (`['docs/corpus/...']`).
- **Indexing:** *(observed)* directory-based on-disk index; the target directory must pre-exist; `writer.commit()` then **`index.reload()`** is required before a searcher sees documents (without it: `num_docs=0`, empty results).
- **Tokenization/config:** *(observed)* default tokenizer = lowercase + alphanumeric split, no stemming; default query parser field = `text`, and **`conjunction_by_default=False`** → natural-language queries are OR-ed by default. *(doc)* custom tokenizers, stemming, field boosts, phrase/fuzzy queries available.
- **Ranking:** *(doc)* BM25 with k1=1.2, b=0.75 defaults (documented; different from bm25s/rank_bm25's 1.5). *(observed)* positive scores, engine-normalized.
- **Top-k:** *(observed)* `searcher.search(query, limit=k)` native; returns `SearchResult(hits=[(score, DocAddress)])`.
- **Persistence:** *(observed)* index files persist on disk; on shutdown of a temp dir with a live index we hit `OSError: Directory not empty` (engine holds files) — a cleanup/DX detail.
- **Determinism:** *(interpretation)* deterministic for identical index + query.
- **What our app still controls:** schema fields (our metadata), which fields are searched and boosts, query parsing/conjunction mode, tokenizer choice, k, mapping DocAddress→chunk id.
- **Complexity it removes:** analyzers, inverted index, BM25, segment management, phrase queries — far more engine than a BM25 library.
- **Complexity it introduces:** Rust binary dependency, directory lifecycle, commit/reload visibility semantics, less-transparent scoring internals.
- **Testing/debugging:** good once understood; the commit/reload gotcha and list-typed stored fields are the main DX surprises (*observed*).
- **Limitations:** lexical only; no built-in metadata SQL; API churn risk across versions (`query_parser` → `index.parse_query` changed between docs and 0.26).
- **When to use:** when you want search-engine features (analyzers, phrase/fuzzy/highlighting) in-process without running a server.
- **When not to use:** when plain BM25 over a small corpus suffices and you want minimal dependencies/API surface.
- **Production-scale alternative:** Elasticsearch/OpenSearch (same lineage of ideas, server + cluster), or Quickwit (built on Tantivy).

### C4. rank_bm25 (baseline/reference only)

- **Problem it solves:** minimal, readable Okapi BM25 implementation.
- **Abstraction:** `BM25Okapi(corpus_tokens).get_scores(query_tokens)`.
- **Document representation:** *(observed)* pre-tokenized lists via plain `str.lower().split()` — the app owns all tokenization.
- **Indexing:** *(observed)* in-memory only; no persistence API.
- **Config:** *(observed)* `BM25Okapi` defaults k1=1.5, b=0.75; no stopwords/stemming.
- **Ranking/top-k:** raw scores, manual sorting for top-k.
- **Role:** *(interpretation)* useful as a reference implementation to sanity-check that a chosen tool behaves like textbook BM25; not a production choice (no persistence, no tokenizer strategy, maintenance is minimal).
- **Observed behavior:** its rankings closely track bm25s (same k1/b), with differences concentrated where tokenization differs (e.g. Q5 CG-200 hardware: rank_bm25 put `edge-gateway-hardware` #1 while bm25s put `networking-and-retries` #1 — *(interpretation)* bm25s's tokenizer/stopword handling changed term overlap around "gateway"/"CG-200").

### C5. Documented-only alternatives (NOT installed, NOT run)

- **Elasticsearch / OpenSearch** — distributed full-text engines; analyzers, facets, aggregations, scaling. *Not used here because:* requires a running server + significant RAM (8 GB budget), violating "avoid unnecessary infrastructure" at current scale. *(doc-based)*
- **PostgreSQL FTS** — `tsvector`/`tsquery`/`ts_rank`, plus `pgvector` later for M6 hybrid. *Not used here because:* server database (Docker currently a non-goal); revisit in M6 when a single relational store for FTS+vector becomes genuinely attractive. *(doc-based)*
- **LangChain `BM25Retriever` / LlamaIndex BM25 retriever** — framework-level retriever abstractions over `rank_bm25`-style scoring. *Not used here because:* adopting a framework for M2 would pre-empt the M5 comparison. *(doc-based)*
- **Custom BM25 from scratch** — rejected by default: the educational purpose was served by M1; only a specific architectural reason would reopen this.

## D. Query observations (9 queries, k=5)

Queries (identical across all candidates):

1. `How are retries handled?` — retry terminology
2. `What sampling interval does the gateway use?` — near-miss 15 s vs 45 s
3. `How many requests per minute are allowed?` — near-miss 600/min vs 60/min
4. `How are engineers notified when something fails at night?` — terminology/synonym
5. `What hardware does the CG-200 gateway use?` — answer concentrated in one document
6. `Who do we escalate to when an incident drags on?` — overlapping concepts (runbook + monitoring)
7. `What is the exponential backoff retry schedule?` — lexical-friendly exact match
8. `How do employees log in to the system?` — lexical limitation (docs say "authentication/credentials/tokens")
9. `When does the ingestion pipeline flush queued batches?` — lexical-friendly + overlap

*(observed)* consistent behavior across all four candidates:

- **Q7, Q9 (lexical-friendly):** all four rank `networking-and-retries :: Retry Policy` / `ingestion-pipeline :: Batching and Flushing` at #1–#2. Lexical retrieval does its job when vocabulary overlaps.
- **Q3 (600 vs 60):** all four rank `api-rate-limits :: Default Limits` #1 and `authentication-and-tokens :: Identity Endpoint Limits` #2 — both near-miss documents surfaced, ordering identical in spirit. Discriminating 600 *from* 60 requires understanding the *number in context*, which is beyond term overlap (Q3's challenge is passed to M3's evaluation, not solved here).
- **Q2 (15 s vs 45 s):** the authoritative edge-gateway chunk ranked #2–#4 in most runs while `ingestion-pipeline` (45 s) or `networking` ranked #1 in three of four. *(interpretation)* lexical retrieval does not reliably resolve near-miss numerics — a core expected limitation, evidence for later vector/hybrid milestones.
- **Q4, Q8 (synonym gap):** the authoritative documents (`monitoring-and-alerting`, `authentication-and-tokens`) did **not** reach top-5 for any candidate. *(interpretation)* confirmed lexical limitation with paraphrased vocabulary ("log in" vs "authentication", "notified at night" vs "page on-call").
- **Q5 (single-doc):** FTS5, tantivy, rank_bm25 ranked `edge-gateway-hardware` #1; bm25s ranked `networking-and-retries` #1 with edge-gateway #2 — tokenization differences changed the outcome (*observed* divergence).
- **Q6 (overlapping):** runbook/monitoring-family chunks surfaced on top for bm25s/FTS5/rank_bm25; tantivy's OR-default query ranked an ingestion chunk #1 — *(interpretation)* the default conjunction mode matters as much as scoring for natural-language queries.
- **Q1:** top-1 differed by candidate (networking for bm25s/rank_bm25; architecture glossary for FTS5/tantivy) while the same four documents occupied the top-4 almost everywhere. *(interpretation)* scoring function matters less than query semantics/tokenization for this corpus.

## E. Integration observations

- All four fit behind `retrieve(query, k)` with a thin adapter; none leaked into other application concerns.
- **Query semantics differ per engine:** FTS5 needs an explicit operator strategy (AND default returned nothing); tantivy needs conjunction mode awareness (OR default); bm25s/rank_bm25 take raw token lists — the "query parser" is *our* code in all cases.
- **Metadata mapping:** all engines can carry/return our `source_file`/`section` (FTS5 as columns, tantivy as stored fields, bm25s/rank_bm25 via parallel index→record mapping).
- **DX friction observed:** bm25s tokenized-query/vocabulary coupling; tantivy commit→reload visibility + list-typed stored fields; FTS5 negative score ordering; rank_bm25 does everything manually.
- **Score interpretability:** all expose raw scores, but scales/signs differ (FTS5 negative). Only FTS5 gives interactive SQL for debugging.

## F. Persistence / indexing observations

| Candidate | Artifact | Rebuildable from chunks.jsonl? | Notes *(observed)* |
|---|---|---|---|
| bm25s | saved index file (save/load API present) | yes | in-memory build each run is also trivial at 65 chunks |
| SQLite FTS5 | `.db` file (or `:memory:`) | yes | real persistence; survives processes; queryable |
| tantivy | index directory | yes | files on disk; requires dir lifecycle handling |
| rank_bm25 | none | n/a | in-memory only |

*(interpretation)* In all cases the index is a **derived artifact** — `chunks.jsonl` stays canonical, which preserves the M1 architecture rule.

## G. Configuration observations

- **k1/b defaults differ:** bm25s `1.5/0.75`, rank_bm25 `1.5/0.75`, tantivy `1.2/0.75` *(doc)*.
- **Tokenizer defaults differ:** bm25s (stopwords optional, stemming available), FTS5 `unicode61` (no stemming; porter opt-in), tantivy lowercase+alphanumeric (no stemming), rank_bm25 naive split (keeps stopwords).
- **Conjunction defaults differ:** FTS5 AND, tantivy OR, BM25 libraries N/A (all terms scored).
- **Score conventions differ:** FTS5 negative/lower-better; others positive/higher-better.
- None of these defaults are *wrong*; each is a decision the application must make consciously.

## H. Trade-offs (qualitative, no scoring)

- **bm25s ↔ simplicity & speed vs. engine features & project footprint.**
- **SQLite FTS5 ↔ zero-dependency SQL integration & persistence vs. query-semantics care (AND default, score sign) and modest analyzer set.**
- **tantivy ↔ richest search-engine capability in-process vs. Rust binary, directory lifecycle, commit/reload semantics, faster API churn.**
- **rank_bm25 ↔ maximal readability/reference value vs. no persistence, no tokenizer strategy, not production-oriented.**
- Ranking outputs were *more similar than different* on this 65-chunk corpus; the differentiating evidence is operational (persistence, query semantics, config surface, DX), not quality scores.

## I. What remains under our application's control

Regardless of candidate:
- `chunks.jsonl` as the canonical artifact; the index is derived.
- The `retrieve(query, k)` boundary and its result shape (text, source, section, score).
- Query parsing/tokenization strategy before it reaches the engine.
- Metadata schema and what gets indexed vs. stored.
- Top-k and any score normalization for display.
- Rebuild/refresh procedure for the index.
- M3's evaluation harness decides *quality* claims; this spike only established architectural fit.

## J. Open questions for ADR-001 (+ spike limitations)

Limitations of this spike *(interpretation)*:
- 65 chunks / 9 queries is far too small to support quality claims; overlaps in top-k are expected and meaningless to rank.
- We measured no latency/throughput (irrelevant at this size; note only).
- bm25s `save/load` round-trip and tantivy reopen-from-disk persistence were not exercised end-to-end.
- No stemming/phrase-query configurations were compared — defaults only.
- English-only queries; single corpus; synthetic documents.
- Scores across engines are not comparable; nothing here says one engine "retrieves better".

Open questions for ADR-001:
1. Do we optimize for **zero new dependencies** (FTS5, stdlib) or **library-managed BM25 semantics** (bm25s) or **search-engine features** (tantivy)? Which better fits "production-oriented but no premature complexity"?
2. Who owns query parsing — our adapter (explicit, testable) vs engine defaults (AND/OR divergence observed)?
3. Which persistence story do we want: SQL file, index directory, index blob, or rebuild-on-start (fine at this scale)?
4. How important is SQL-based debuggability (FTS5) vs pure-Ranking-API simplicity (bm25s)?
5. Does adding a Rust binary dependency (tantivy) earn its place given current needs, or is that M7+ territory?
6. What does the ADR need to say about the path to M6 (vector) and M7 (hybrid) — e.g. FTS5's absence of an easy vector companion vs SQLite+pgvector-like single-store futures vs engine-agnostic adapters?
7. Should `rank_bm25` remain referenced in the ADR as a baseline/teaching reference, and should `bm25s`'s DX sharp edges (tokenized-query coupling) be called out as a risk?
8. Confirm Tantivy's gate status: **install passed trivially** — decide whether it is still evaluated as a live candidate or documented as "capable but heavier than needed" (*decision belongs to the ADR, based on fit, not scores*).
