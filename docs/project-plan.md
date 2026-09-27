# Engineering Knowledge Assistant — Project Plan

**Status:** Approved
**Version:** 2.0
**Revision:** M2 strategy — evaluate and adopt production-oriented capabilities

**Revision history:**
- v1.0 — original plan (M0/M1): build foundational components ourselves (Approved).
- v2.0 — M2+ strategy: evaluate ecosystem alternatives and record architecture decisions; M0/M1 frozen as the understanding layer (Approved).

## 1. Purpose

Build a small Engineering Knowledge Assistant as a learning project for modern AI application engineering.

The system will eventually allow engineers to ask questions about technical documents and receive answers grounded in those documents with verifiable citations.

The main goals are:
- Understand how RAG works internally.
- Learn modern AI application engineering.
- Learn retrieval evaluation.
- Learn how to use coding agents as engineering collaborators.
- Evolve the system incrementally.

From M2 onward, the project is a production-oriented AI Engineering laboratory. The goal is not to
implement every algorithm ourselves, but to learn how an experienced AI Engineer would solve a real
RAG system using the current ecosystem — and to record each choice as an explicit architectural
decision.

The engineering cycle for every major technology from M2 onward:

1. Understand the abstraction
2. Evaluate alternatives
3. Make an architecture decision
4. Implement using the selected production-oriented tool
5. Measure / evaluate
6. Document trade-offs

## 2. Roles

### Engineering Lead

The human Engineering Lead owns:
- Problem definition
- Scope
- Requirements
- Architecture
- Trade-offs
- Priorities
- Acceptance criteria
- Approval of implementation plans
- Review of implementation

### Coding Agent

The coding agent acts as a Senior/Staff Engineer and is responsible for:
- Inspecting the repository
- Proposing implementation approaches
- Implementing approved changes
- Writing tests
- Debugging
- Refactoring
- Documenting implementation

The agent must not silently expand scope.

## 3. Constraints

- Budget: $0
- Language: Python
- Python version: 3.13
- Existing Conda environment: `ai-engineering`
- Do not create another virtual environment
- Local-first and privacy-conscious
- Prefer the simplest solution that validates the current hypothesis
- Introduce complexity only when justified
- The Engineering Lead must understand the resulting code

## 4. MVP

The project has two phases.

### Phase A — Retrieval

The system must work without an LLM.

Example:

`kba search "How are retries handled?"`

The command returns ranked chunks containing:
- Text
- Source file
- Section
- Score

Retrieval must be useful and testable by itself.

### Phase B — Generation

Only after retrieval and evaluation work will an LLM be introduced.

The LLM will receive:
- User question
- Retrieved context

And produce:
- Grounded answer
- Source citations

The LLM provider remains undecided until M4.

## 4.5 M0/M1 — The frozen understanding layer

M0 and M1 intentionally built the foundational components by hand — document ingestion, document
representation, chunking, metadata, persistence, deterministic processing, and module boundaries —
so that these concepts could be understood directly.

M0 and M1 are now the **frozen understanding layer** of this project. The following must not be
modified unless a concrete compatibility issue is demonstrated:
- `kba/loader.py`, `kba/chunker.py`, `kba/writer.py`
- Existing tests and fixtures
- `docs/corpus/**`
- The `chunks.jsonl` schema
- `ingest` CLI behavior and exit codes

Later milestones must be able to recognize which parts of the M1 implementation a new technology
or framework abstracts. M1 is the reference against which later abstractions are compared.

## 5. Non-goals

The following are currently out of scope:

- Web UI
- Kubernetes
- Multi-user functionality
- Authentication
- PDF processing
- Chat memory
- Multi-turn conversations
- Streaming
- Fine-tuning
- Background ingestion
- Folder watching

The following are **conditional** — allowed only when a problem justifies them and an Architecture
Decision Record documents the evaluation:

- Databases, vector databases, search engines (embedded stores considered per decision; server
  databases require an ADR plus evidence)
- LangChain, LlamaIndex (compared in M5; adoption requires an ADR)
- LangGraph (evaluated separately in M9)
- Agents
- MCP
- Query rewriting
- HyDE
- Reranking before evidence justifies it
- Docker / local services
- Production deployment

## 6. Initial Corpus

M0 will contain approximately 10 small synthetic Markdown documents.

They will describe one coherent fictional engineering system.

The corpus should include:
- Distinct topics
- Some overlapping concepts
- Near-miss information
- Enough detail for meaningful retrieval questions
- Deliberate retrieval challenges

The documents must not contain private company information, personal information, credentials, or secrets.

## 7. Supported Formats

Initial formats:
- `.md`
- `.txt`

PDF is excluded from the current scope.

## 8. Functional Requirements

FR1 — Load Markdown and plain-text files from a configured directory.

FR2 — Split documents into chunks while preserving source file, section, and source location metadata.

FR3 — Persist the processed chunks/index locally.

FR4 — Retrieve the top-k relevant chunks for a query, including text, source, section, and score.

FR5 — Later, generate answers only from retrieved context and communicate uncertainty when context is insufficient.

FR6 — Later, generated answers must identify their source material.

FR7 — Maintain approximately 15–20 evaluation questions with expected source documents and measure recall@5.

## 9. Non-functional Requirements

- Simple enough to understand in one walkthrough.
- Target approximately 500 lines of application code for the MVP.
- Total cost: $0.
- Local-first and privacy-conscious.
- Retrieval and generation must remain independently testable.
- Outputs must be traceable to source documents.

## 10. Architecture

Initial architecture:

INGESTION
docs/ -> load -> chunk -> index -> local index

QUERY
question -> retrieve() -> top-k chunks -> Phase A: print results -> Phase B: prompt LLM -> answer + citations

Two important boundaries:
1. retrieve() — retrieval can evolve independently.
2. llm — the LLM provider can change independently.

Storage rule: `chunks.jsonl` is the canonical, source-of-truth artifact. Every future index
(BM25, FTS, vector) is a derived artifact built from it — never a replacement for it.

```
Application
    ↓
retrieve(query, k)            ← stable boundary
    ↓
implementation chosen in ADR-001
    ↑
chunks.jsonl (canonical)  →  derived index artifact
```

## 11. Technology Decisions

### Language
Python 3.13.

### Environment
Use existing Conda ai-engineering; no other manager. Dependencies are declared in
`pyproject.toml` and installed with `pip` inside the existing conda environment. No new
environment is ever created.

### CLI
Simple CLI, preferably argparse.

### Storage
`chunks.jsonl` remains canonical. Embedded stores (e.g. SQLite/FTS5) and derived local indexes
are allowed with an ADR. Server databases require an ADR plus evidence.

### Retrieval
Lexical retrieval is evaluated in M2 among library / embedded full-text search /
(search-engine and framework alternatives are documented, not necessarily implemented) / custom
alternatives. The selection is recorded in ADR-001. Embeddings arrive in M6 behind the same
`retrieve()` boundary.

### Frameworks
Not adopted by default. LangChain and LlamaIndex are compared in M5 against our raw-SDK baseline.
LangGraph is evaluated separately in M9 as workflow/state orchestration infrastructure. Adoption
in any case requires an ADR.

### LLM
Provider undecided; local/free API/multiple providers possible; Mac 8GB; no Ollama before M4.

## 12. Evaluation

Approximately 15–20 golden questions with expected source documents. Measure recall@5. Compare BM25 vs embeddings vs optional hybrid.

The formal evaluation harness lands in M3. M2 performs understanding-oriented smoke checks only
(8–10 representative queries), with no scoring tables and no winner declarations.

## 13. Milestones

| # | Milestone | Core question | Decision artifact |
|---|---|---|---|
| M0 | Foundation | *(done)* | — |
| M1 | Ingestion & chunking — loaders, heading-aware chunking, overlap, metadata, chunks.jsonl | *(done — frozen understanding layer)* | — |
| M2 | Retrieval Engineering (lexical): how does a real Python app do lexical retrieval? | Spike over candidates, select via ADR | ADR-001 retrieval strategy |
| M3 | Retrieval Evaluation: is retrieval actually good? Golden set, recall@5, MRR/nDCG, baselines | — | Eval harness + doc |
| M4 | RAG fundamentals using a provider SDK: prompt + context + citations, structured output, no framework | Which model/provider? | ADR-002 model/provider |
| M5 | RAG framework comparison: our raw-SDK baseline vs LangChain vs LlamaIndex — do they earn their place? | Which framework, if any? | ADR-003 RAG framework |
| M6 | Vector Retrieval: semantic recall; store options under 8 GB / no-Docker constraint | Which vector store? | ADR-004 vector store |
| M7 | Hybrid + Reranking: fusion strategies, cross-encoder rerankers, when reranking pays off | Is hybrid/reranking justified? | ADR-005 hybrid/rerank |
| M8 | Advanced RAG — **evidence-gated**: query rewriting, HyDE, contextual compression, only if metrics justify | Do these techniques help us? | ADR if a technique is adopted |
| M9 | LangGraph / agentic workflows: state, branching, persistence, human-in-the-loop — evaluated separately from M5 | Is orchestration infrastructure justified? | ADR-006 orchestration |
| M10 | MCP / tools: tools vs MCP, when a protocol boundary is warranted | — | ADR-007 |
| M11 | Evaluation & Observability 2.0: answer eval, RAG-as-judge, tracing (local) | — | ADR-008 observability |
| M12 | Production Architecture: what would deployment require; review and supersede all ADRs | — | Final architecture record |

M5 and M9 are deliberately distinct: M5 compares data/application building-block frameworks
(LangChain, LlamaIndex) against our raw baseline; M9 evaluates LangGraph alone as stateful
workflow/agent orchestration infrastructure. The three are not interchangeable.

Each milestone follows the cycle: understand → evaluate → decide → implement → measure →
document trade-offs. No milestone starts before the Engineering Lead approves the prior decision
record.

## 14. Engineering Principles

1. Start simple.
2. Measure before optimizing.
3. Own the application architecture; delegate mature capabilities — understand the abstraction rather than reinventing it.
4. Introduce complexity only when justified.
5. Keep retrieval independently testable.
6. Treat citations as correctness.
7. Evaluate retrieval independently from generation.
8. Keep scope explicit.
9. Agent proposes; Engineering Lead decides.
10. Agent must not silently expand scope.
11. Use small reviewable tasks.
12. Every milestone must be runnable and inspectable.
13. No code is accepted that the Engineering Lead cannot explain conceptually.
14. Every architecturally significant technology change is recorded as an Architecture Decision Record.
15. Evaluation is continuous from M3 onward.
16. No mature algorithm is implemented from scratch without a stated architectural or educational reason.

## 15. Current Open Decisions

Decided:
- Retrieval strategy — SQLite FTS5 (Python `sqlite3`) as lexical retrieval engine, accepted
  2026-09-24; see `docs/decisions/001-retrieval-strategy.md` (bm25s = designated alternative;
  retrieval quality to be evaluated in M3).
- Test framework — **pytest** (2026-09-27): the project's official test runner;
  development-only dependency (`pytest>=8`), no plugins, no coverage tooling yet. The
  full suite (133 tests) was migrated from unittest with a per-file count ledger
  proving behavior equivalence. `python -m pytest` is the documented command.

Open:
1. LLM provider (M4).
2. RAG framework (M5).
3. Vector store (M6).
4. Agent orchestration (M9).
5. Additional metrics beyond recall@5 (M3).
6. Real/public documents after MVP.

## 16. Current Status

Completed:
- Python 3.13 environment
- Conda environment
- OpenCode
- Dedicated Git repository
- .gitignore
- VS Code configuration
- Initial Git commit
- Architecture and milestones approved
- M0 Foundation
- M1 Document Ingestion and Chunking (frozen understanding layer)

Current milestone: M2 Retrieval Engineering.

ADR-001 is **Accepted**: SQLite FTS5 is the lexical retrieval engine
(`docs/decisions/001-retrieval-strategy.md`).

Next task: implement the retrieval layer behind `retrieve(query, k)` — explicit
`python -m kba index` build step, `python -m kba search`, derived FTS5 database
(not committed), query-parsing policy owned by the application, and tests.

Before implementation, the coding agent must read this document and propose exact changes.

The coding agent must wait for approval before modifying files.

## 17. Decision records

Architecturally significant decisions are recorded as Architecture Decision Records (ADRs) in
`docs/decisions/`, named `NNN-kebab-title.md`, with an index at `docs/decisions/README.md`.

Each ADR uses these headings:

1. Context
2. Problem
3. Evaluation criteria
4. Alternatives considered
5. Decision
6. Rationale
7. Trade-offs
8. Consequences
9. Status

Rules:
- Status lifecycle: `Proposed → Accepted → Superseded by NNN`. ADRs are immutable once accepted;
  corrections create a new ADR.
- One ADR per architecturally significant decision (changes a boundary, a persistence model, or
  adds a framework or infrastructure). Bug fixes and configuration tweaks do not get ADRs.
- Every ADR lists rejected alternatives with reasons — that is the teaching artifact.
- Evaluation is qualitative. No numerical rankings, scores, or "best/winner" language; the
  decision is justified as a fit to this project's requirements.
- Initial numbering: 001 retrieval strategy (M2). Future ADRs (002 model/provider, 003 RAG
  framework, 004 vector store, 005 hybrid/rerank, 006 orchestration, 007 MCP/tools, 008
  observability) are reserved but must not be created before their milestone.
