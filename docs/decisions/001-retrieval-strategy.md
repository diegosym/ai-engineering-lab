# ADR-001: Retrieval Strategy — Lexical Retrieval Engine

| | |
|---|---|
| **Status** | **Accepted** |
| **Date** | 2026-09-24 |
| **Decision scope** | Lexical retrieval engine for the permanent retrieval layer (M2's `retrieve(query, k)` implementation) |
| **Evidence** | `spike/m2-lexical-retrieval/NOTES.md`, `spike/m2-lexical-retrieval/raw-results.txt`, `spike/m2-lexical-retrieval/run_spike.py` |
| **Supersedes** | — (first ADR) |

---

## 1. Context

M0 and M1 built the ingestion pipeline by hand as the project's frozen understanding layer:
documents → loader → document → chunker → chunks + metadata → `chunks.jsonl`. That pipeline, its
tests, and the `chunks.jsonl` schema are frozen.

M2 must now provide lexical retrieval behind the stable application boundary `retrieve(query, k)`.
The project's M2+ philosophy requires that a mature, well-established capability (BM25/full-text
search) be delegated to a production-oriented tool rather than reimplemented, and that the choice
be recorded as an explicit architectural decision.

Environment constraints that bound this decision:

- Python 3.13, conda `ai-engineering`, **no new environments**
- Budget $0, local-first, Mac Intel (x86_64), 8 GB RAM
- No Docker, no servers, no unnecessary infrastructure
- `chunks.jsonl` is the **canonical artifact**; any index is derived from it
- The Engineering Lead must be able to explain the resulting design conceptually

## 2. Problem

Choose the lexical retrieval engine for the permanent retrieval layer such that:

1. `chunks.jsonl` remains the canonical source of truth; the index is a rebuildable derived
   artifact.
2. The application stays decoupled from the engine behind `retrieve(query, k)`.
3. The engine is production-oriented (mature, maintained, deterministic, testable) without
   introducing premature production complexity.
4. The choice is justified by fit to *this project's* requirements — not by popularity and not by
   unmeasured retrieval-quality claims.

## 3. Evidence base — what M2 actually observed

**Method:** 65 chunks (existing `chunks.jsonl`, not regenerated) × 9 representative queries, k=5,
run against four candidates. All four completed end-to-end with **zero runtime errors in the final
run**. No benchmark harness was built; no aggregate scores were computed.

**Observations (observed behavior — not quality claims):**

- **Rankings were broadly similar** across candidates. On this 65-chunk corpus the differentiating
  evidence is operational (query semantics, persistence, config surface, DX), not result ordering.
- **M2 is NOT sufficient to make a retrieval-quality claim.** 9 queries over 65 synthetic chunks
  cannot support "engine X retrieves better". Retrieval quality is M3's job.
- **Q4/Q8 — synonym gap:** the authoritative documents (`monitoring-and-alerting`,
  `authentication-and-tokens`) missed the top-5 for **every** candidate. This confirms lexical
  retrieval's known vocabulary limitation (evidence for M6/M7, not a defect of any candidate).
- **Q2 — numerical near-miss (15 s vs 45 s):** the authoritative chunk ranked #2–#4 in most runs;
  another document took #1 in three of four candidates. Term overlap does not resolve numbers in
  context.
- **Q6 — conjunction behavior differences:** on the verbose query, engines with OR-like semantics
  surfaced an irrelevant #1 result, while tighter semantics kept escalation-related chunks on top.
- **Q5 — tokenizer differences:** the #1 result differed (bm25s → `networking-and-retries.md`;
  FTS5/tantivy/rank_bm25 → `edge-gateway-hardware.md`) — tokenization changed the outcome, not
  the scoring formula.
- **FTS5 AND-default:** all **9 of 9** natural-language queries returned **zero rows** under
  space-joined MATCH (default AND). The spike re-ran them with OR-joined terms. Implication: the
  application must own query parsing/operator choice regardless of which engine is selected.
- **Tantivy OR-default:** its query parser defaults to disjunction
  (`conjunction_by_default=False`), which produced the irrelevant #1 on verbose Q6.
- **Score conventions differ:** FTS5 `bm25()` returns **negative** values (lower = better); bm25s,
  tantivy, and rank_bm25 return positive values (higher = better).
- **Tokenizer/conjunction defaults differ:** FTS5 = `unicode61` (no stemming, AND), tantivy =
  lowercase+alphanumeric (no stemming, OR), bm25s = optional stopwords/stemming (scores all query
  terms), rank_bm25 = naive split keeping stopwords.
- **k1/b defaults differ:** bm25s and rank_bm25 use k1=1.5, b=0.75; tantivy documents k1=1.2,
  b=0.75.

**Installation gate results:** all four installed or were available without friction —
`bm25s 0.3.11`, `tantivy 0.26.2` (prebuilt cp313/macOS x86_64 wheel, no compilation),
`rank-bm25 0.2.2`; SQLite FTS5 available in the standard library (SQLite 3.45.3).

## 4. Evaluation criteria (qualitative — no weights, no scores)

The 11 criteria established by the project:

1. Fit to current requirements
2. Operational complexity
3. Dependency / maintenance health
4. Configurability
5. Retrieval capabilities
6. Determinism
7. Persistence / indexing model
8. Scalability path
9. Explainability / debuggability
10. Compatibility with our `retrieve(query, k)` boundary
11. Future path to vector / hybrid retrieval

Per project policy, comparison is qualitative. Terms such as "best", "winner", or numerical
rankings are deliberately absent; the decision is justified as a **fit to this project's
requirements**.

## 5. Alternatives considered

### Evaluated in the M2 spike (runnable candidates)

| Candidate | Fit to requirements | Operational complexity | Dependencies | Persistence model | Integration surface | Notes |
|---|---|---|---|---|---|---|
| **SQLite FTS5** | Embedded, stdlib, local-first — aligns with all constraints | None (no service, no new package) | **Zero new** (stdlib) | `.db` derived artifact | SQL + FTS5 query semantics (AND-default, negative scores) | Production-proven; SQL debuggability; modest analyzers |
| **bm25s** | In-process BM25 library; one new dependency | Low | `bm25s` + `numpy` | Separate saved index artifact (save/load present) | Small API, but tokenized-query/vocabulary coupling observed as DX friction | Explicit k1/b; library-managed scoring; smaller project footprint |
| **Tantivy 0.26.2** | Capability-rich embedded search engine | Medium — directory lifecycle, commit/reload semantics | Rust binary wheel | Index directory | **Heaviest**: schema, stored-field quirks, query-parser defaults, API churn across versions | Analyzers/phrase/fuzzy/highlighting available; over-featured for current needs |
| **rank_bm25** | Reference-only | Low | `rank_bm25` + numpy | **None** (in-memory) | Entirely manual (tokenization, sorting, persistence) | Documented as **baseline/reference implementation**, not the production choice |

### Documented-only (considered, not implemented — per M2 scope)

- **Elasticsearch / OpenSearch** — server infrastructure, significant RAM footprint; violates
  "avoid unnecessary infrastructure" at current scale. Revisit only if a deployment scenario
  creates the need.
- **PostgreSQL Full Text Search** — server database (Docker currently a non-goal); same SQL mental
  model as FTS5. Natural candidate to re-evaluate in M6 when a combined FTS+vector store may
  become attractive.
- **LangChain `BM25Retriever` / LlamaIndex BM25 retriever** — framework-level retriever
  abstractions. Adopting a framework for M2 would pre-empt the M5 framework comparison; explicitly
  deferred.
- **Custom BM25 from scratch** — rejected: the educational purpose was already served by M1.
  Reopening it would require a specific architectural or educational reason (project principle 16).

## 6. Decision

**SQLite FTS5 (Python standard-library `sqlite3`) is the lexical retrieval engine for M2's
permanent retrieval layer. Accepted by the Engineering Lead on 2026-09-24.**

This decision is based on **architectural fit to the current project requirements, NOT on
retrieval-quality superiority**. No claim is made — and M2 could not support a claim — that FTS5
retrieves better than bm25s, tantivy, or rank_bm25.

**Designated alternative:** `bm25s` is recorded as the alternative that should be **reconsidered
if FTS5's analyzer/relevance capabilities become insufficient**. Reconsideration happens by
superseding this ADR with a new one, with bm25s as the first alternative to re-evaluate.

**Tantivy** is recorded as capability-rich but carrying the heaviest integration surface; it does
not fit the current requirement profile (simplicity, minimal dependencies) and is not selected.

**rank_bm25** is recorded as a baseline/reference implementation for teaching and sanity-checking
BM25 behavior, not as the production choice.

### Index architecture (explicit build step)

The index is built by an explicit command — **not** automatically during search:

```
documents
  ↓  ingest
chunks.jsonl            ← canonical
  ↓  index (python -m kba index)
derived FTS5 database   ← derived, rebuildable, not committed
  ↓  search (python -m kba search "query")
retrieve(query, k)
```

- The FTS5 database is a **derived artifact**: rebuildable from `chunks.jsonl` at any time.
- `chunks.jsonl` is never regenerated or modified by indexing.
- The database must **not be committed**; the `.gitignore` entry is added during the
  implementation step (not in this ADR-closing step).

## 7. Architectural responsibility retained by the application

The FTS5 engine is an **implementation detail behind `retrieve(query, k)`**. No SQLite-specific
types, SQL syntax, FTS5 MATCH semantics, or negative score conventions may leak into the rest of
the application. The application owns:

- **Query parsing** — converting the user's query string into engine input (M2 proved this is
  unavoidable: FTS5's AND-default returned zero rows for natural-language queries). The
  implementation must **not blindly expose FTS5's default AND behavior**.
- **Query normalization / tokenization policy** — casing, stopwords, stemming decisions.
- **Conjunction behavior** — AND vs OR vs phrase semantics explicitly defined by us, not inherited
  from engine defaults.
- **Metadata schema / filtering** — which chunk metadata is indexed, stored, or filtered on.
- **Top-k semantics** — what `k` means, ties, minimum-score cutoffs.
- **Score normalization / presentation** — including FTS5's negative-score convention
  (lower = better).
- **Index rebuild procedure** — building/refreshing the derived database from canonical
  `chunks.jsonl` via `python -m kba index`.
- **The `retrieve(query, k)` contract** — result shape (text, source, section, score) and
  determinism guarantees.

These behaviors are **defined by this ADR as the application's responsibility but are NOT
implemented in this ADR-closing step**; they belong to the retrieval-layer implementation task.

## 8. Persistence and indexing implications

- **`chunks.jsonl` remains canonical** in all cases; every index is derived and rebuildable.
- **FTS5 (selected):** a `.db` file (or `:memory:` for tests) holds the derived index;
  rebuild = re-ingest from `chunks.jsonl` via `python -m kba index`. SQL provides interactive
  inspection. Not committed (git-ignored at implementation time).
- **bm25s (designated alternative):** a separate saved index artifact via `save()/load()`;
  rebuild = re-index from `chunks.jsonl`. Round-trip persistence was **not exercised** in M2.
- **Tantivy (not selected):** an index directory with lifecycle handling (pre-existing dir,
  commit/reload visibility).
- **rank_bm25 (baseline):** no persistent index; purely in-memory.

## 9. Rationale (fit to requirements, not quality)

- **Constraints:** FTS5 adds *zero* dependencies to a deliberately bare environment — the
  strongest possible fit for "$0, local-first, no unnecessary infrastructure". bm25s adds
  `bm25s` + `numpy`; tantivy adds a Rust binary.
- **Operational complexity:** FTS5 requires no index-directory lifecycle, no reload semantics, no
  vocabulary-coupled query API — the two integration surfaces M2 flagged as friction (FTS5's
  AND-default and negative scores) both land in code this application must own anyway per
  section 7.
- **Debuggability:** SQL inspection of the index is uniquely interactive among the candidates
  (criteria 9), valuable while M3 builds the evaluation harness.
- **Persistence model:** a single derived `.db` artifact next to the canonical `chunks.jsonl`
  keeps the storage story explainable in one walkthrough (NFR).
- **Boundary compatibility:** all four candidates fit behind `retrieve(query, k)`; FTS5's engine
  specifics stay confined to one adapter module (criteria 10).
- **Maturity:** SQLite FTS5 ships with Python, is battle-tested across decades of deployments,
  and removes the dependency-health risk attached to a small third-party library (criteria 3).
- **Honest limitation:** FTS5's analyzer set (English-centric options, stemming opt-in) is more
  modest than tantivy's — acceptable now, and explicitly the trigger condition for superseding
  this ADR (toward bm25s) if evidence arises.

## 10. Trade-offs

Accepted:
- We take on query-parsing responsibility (operator choice, tokenization policy, conjunction
  behavior, score normalization) in application code — deliberate, since M2 proved no engine
  default is right for natural-language queries.
- We accept FTS5's negative score convention behind our own score presentation.
- We accept a more modest analyzer/relevance feature set than a search engine provides.
- We accept that the FTS5-vs-bm25s quality relationship is **unmeasured** until M3.

Given up by not selecting the others:
- bm25s: explicit, library-managed BM25 semantics (k1/b in our hands as first-class config).
- tantivy: phrase queries, custom analyzers, highlighting, engine-grade relevance features.
- rank_bm25: maximal code transparency (but no persistence or tokenizer strategy at all).

## 11. Consequences

**Positive:**
- Zero new runtime dependencies for retrieval; environment stays bare.
- `chunks.jsonl` canonicality preserved; index is a rebuildable, uncommitted `.db` artifact.
- SQL-based inspection and testing of retrieval behavior.
- The application's retrieval boundary and query-parsing policy remain fully under our control
  and independently testable.
- A clear supersession path (bm25s first, then tantivy/PG FTS) if requirements change.

**Negative / risks:**
- Query parsing, conjunction policy, and score normalization must be implemented and tested by us
  (new application code to own and explain).
- FTS5 analyzer limitations could surface later (e.g., stemming demands in M3 or M7) — trigger for
  reconsidering the designated alternative.
- FTS5 quality relationship to the alternatives is unknown until M3 — this ADR must not be
  cited as a quality endorsement.
- SQLite's bundled FTS5 configuration is build-dependent (verified present here: SQLite 3.45.3).

**Operational implications:**
- `kba` gains an explicit index-build step (`python -m kba index`); `search` never builds
  implicitly — rebuild determinism must be covered by CLI/tests.
- Index staleness policy: the database is rebuilt from `chunks.jsonl` whenever ingestion changes
  it (procedure implemented with the CLI).
- No services, daemons, or background processes are introduced.
- `.gitignore` will ignore the derived `.db` artifact (implementation step).

## 12. Separation of concerns

- **M2 observations:** section 3 — behavior actually produced by running the spike; no
  interpretation beyond what the outputs show.
- **Architectural implications:** sections 6 (index architecture), 7, 8 — what the evidence means
  for our boundaries and storage model.
- **Decision rationale:** sections 6, 9, 10 — requirement-based reasoning for the selection.
- **Intentionally deferred to M3:** every statement about *retrieval quality*. M3 builds the
  golden-question harness (recall@5, MRR/nDCG) and will compare retrieval approaches with
  measurements. **M2 and M3 must not be conflated:** M2 answered "how would a production-oriented
  Python app do lexical retrieval, and what does each option imply architecturally?" — M3 will
  answer "how well does our retrieval actually work?". Nothing in this ADR pre-judges M3's
  findings; if M3 evidence contradicts this decision, this ADR gets superseded with data.

## 13. Review resolutions (Engineering Lead, 2026-09-24)

1. **Decision:** SQLite FTS5 accepted as the lexical retrieval engine — for architectural fit,
   not quality superiority (explicitly recorded in sections 6 and 12).
2. **Location conflict resolved:** ADRs live in `docs/decisions/` with `NNN-kebab-title.md`
   naming (this file); `docs/adr/` is not used. `docs/project-plan.md` §17 and the README align.
3. **Index-build UX decided:** explicit `python -m kba index`, then
   `python -m kba search "query"`; no implicit build during search.
4. **Derived database policy:** rebuildable from `chunks.jsonl`, never committed; `.gitignore`
   entry added during implementation; `chunks.jsonl` itself untouched.

## 14. Status

- **Status:** **Accepted** (previously: Proposed, 2026-09-24)
- **Date:** 2026-09-24
- **Decision scope:** Lexical retrieval engine for the permanent retrieval layer
- **Next:** retrieval-layer implementation task (`kba index`, `kba search`,
  `retrieve(query, k)` adapter, query-parsing policy, tests, `.gitignore` entry) — **not started
  by this ADR-closing step**.
