# kba — Engineering Knowledge Assistant

A small local-first assistant that lets engineers ask questions about technical
documents and receive answers grounded in those documents with verifiable
citations.

**Status: M0–M3 complete — M4 (RAG fundamentals) next. M0/M1 frozen as the
understanding layer.**

The full architecture, requirements, and milestone definitions live in
[docs/project-plan.md](docs/project-plan.md). That document is the source of
truth; this README is a summary.

## Philosophy

- Understand the abstraction; don't unnecessarily reinvent the abstraction.
- Every major technology must earn its place through an explicit architectural
  decision.
- Don't introduce a framework because it's popular; introduce it when the
  problem justifies the abstraction.

M0 and M1 built ingestion, chunking, metadata, and persistence by hand as the
**frozen understanding layer**. From M2 onward the project evaluates
alternatives, decides with an ADR, adopts production-oriented tools, measures,
and documents trade-offs.

## Constraints

- **Python 3.13**
- **Existing Conda environment `ai-engineering`** — no other environment is
  created; declared dependencies are installed with `pip` inside it
- **Budget: $0**
- **Local-first and privacy-conscious**
- Simplest solution that validates the current hypothesis

## Repository layout

```
.
├── README.md                 # this file
├── pyproject.toml            # project metadata + dependencies
├── chunks.jsonl              # canonical chunk store (derived from docs/corpus)
├── docs/
│   ├── project-plan.md       # approved plan — source of truth
│   ├── decisions/            # ADRs (index + template)
│   ├── eval/                 # M3: golden dataset, baseline results, report
│   └── corpus/               # synthetic retrieval corpus (10 documents)
│       ├── architecture-overview.md
│       ├── edge-gateway-hardware.md
│       ├── networking-and-retries.md
│       ├── ingestion-pipeline.md
│       ├── storage-and-retention.md
│       ├── api-rate-limits.md
│       ├── authentication-and-tokens.md
│       ├── monitoring-and-alerting.md
│       ├── deployment-and-rollout.md
│       └── troubleshooting-runbook.md
├── kba/                      # application package (ingestion, retrieval,
│                             #   metrics, evaluation, CLI)
├── tests/                    # unit + e2e tests (M0–M3, 293 passing)
├── .gitignore
└── .vscode/settings.json
```

`docs/corpus/` is the configured corpus directory. Only files inside it are
meant to be loaded for retrieval; `docs/project-plan.md` is project
documentation and must never enter the index. `chunks.jsonl` is the canonical
artifact; any future retrieval index is derived from it. `docs/eval/` holds the
M3 evaluation artifacts: the frozen golden dataset, the recorded baseline
results, and the evaluation report.

## Architecture decisions

Architecturally significant choices are recorded as ADRs in
[docs/decisions/](docs/decisions/), which holds the index and template. Each
ADR documents context, problem, evaluation criteria, alternatives, decision,
rationale, trade-offs, and consequences — qualitatively, with no numerical
rankings.

[ADR-001 — retrieval strategy](docs/decisions/001-retrieval-strategy.md) is
**Accepted**: SQLite FTS5 (Python `sqlite3`) is the M2 lexical retrieval
engine, chosen for architectural fit — **not** for retrieval-quality
superiority; M3 measured its quality against a frozen golden dataset (see
[docs/eval/m3-baseline-report.md](docs/eval/m3-baseline-report.md)). `bm25s` is
the designated alternative if FTS5's analyzer/relevance capabilities prove
insufficient.

## Environment

```bash
conda activate ai-engineering
python --version   # 3.13.x
```

No additional packages are required. ADR-001 selected SQLite FTS5 from the
standard library, so M2 and M3 add **no new runtime dependencies**; any future
dependency will be declared in `pyproject.toml` and installed with `pip` into
this same environment.

## Running tests

```bash
conda activate ai-engineering
python -m pytest            # full suite (testpaths=tests is configured)
python -m pytest tests/test_retrieval.py    # a single file
python -m pytest -q         # quiet mode
```

**pytest is the project's official (and only documented) test runner.**
It is a development-only dependency, declared in `pyproject.toml` under
`[project.optional-dependencies] dev` — the runtime dependency list stays
empty. Install it with `pip install pytest` inside the `ai-engineering`
environment. No pytest plugins are used.

## Milestones

| Milestone | Scope | Status |
|---|---|---|
| M0 | Foundation: repo, metadata, synthetic corpus, docs | done (frozen) |
| M1 | Document ingestion and heading-aware chunking → `chunks.jsonl` | done (frozen) |
| M2 | Retrieval Engineering: lexical retrieval spike, ADR-001 → `kba search` | done |
| M3 | Retrieval Evaluation: golden questions, recall@5 → `kba eval` (report-based; CLI deferred) | done |
| M4 | RAG fundamentals using a provider SDK: generation with citations → `kba ask` | **next** |
| M5 | RAG framework comparison: raw-SDK baseline vs LangChain vs LlamaIndex | planned |
| M6 | Vector Retrieval behind the same `retrieve()` interface | planned |
| M7 | Hybrid retrieval + reranking | planned |
| M8 | Advanced RAG — only if evaluation evidence justifies it | planned |
| M9 | LangGraph / agentic workflows (evaluated separately from M5) | planned |
| M10 | MCP / tools | planned |
| M11 | Evaluation & observability | planned |
| M12 | Production architecture & ADR consolidation | planned |

See [docs/project-plan.md](docs/project-plan.md) for the authoritative
definitions.

## Non-goals

No web UI, Kubernetes, authentication, PDF processing, chat memory, streaming,
fine-tuning, or production deployment. Databases, vector databases, search
engines, LangChain, LlamaIndex, LangGraph, agents, MCP, and reranking are
**conditional** — allowed only when evidence justifies them and an ADR records
the evaluation. The full lists are in the project plan, section 5.

## Corpus disclaimer

All documents under `docs/corpus/` are **fictional and synthetic**. They
describe an invented system ("Cirrus", a building energy-monitoring platform)
created solely to exercise retrieval. They contain no real company
information, no personal information, no credentials, and no secrets.
