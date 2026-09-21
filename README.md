# kba — Engineering Knowledge Assistant

A small local-first assistant that lets engineers ask questions about technical
documents and receive answers grounded in those documents with verifiable
citations.

**Status: M0 Foundation — no application code yet.**

The full architecture, requirements, and milestone definitions live in
[docs/project-plan.md](docs/project-plan.md). That document is the source of
truth; this README is a summary.

## Constraints

- **Python 3.13**
- **Existing Conda environment `ai-engineering`** — no other environment or
  package manager is used
- **Budget: $0**
- **Local-first and privacy-conscious**
- Simplest solution that validates the current hypothesis

## Repository layout

```
.
├── README.md                 # this file
├── pyproject.toml            # project metadata only (no dependencies)
├── docs/
│   ├── project-plan.md       # approved plan — source of truth
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
├── .gitignore
└── .vscode/settings.json
```

`docs/corpus/` is the configured corpus directory. Only files inside it are
meant to be loaded for retrieval; `docs/project-plan.md` is project
documentation and must never enter the index.

## Environment

```bash
conda activate ai-engineering
python --version   # 3.13.x
```

No packages are required at M0. The environment is intentionally bare.

## Milestones

| Milestone | Scope | Status |
|---|---|---|
| M0 | Foundation: repo, metadata, synthetic corpus, docs | **current** |
| M1 | Document ingestion and heading-aware chunking → `chunks.jsonl` | planned |
| M2 | BM25 retrieval → `kba search` | planned |
| M3 | Evaluation: golden questions, recall@5 → `kba eval` | planned |
| M4 | LLM generation with citations → `kba ask` | planned |
| M5 | Embedding retrieval behind the same `retrieve()` interface | planned |
| M6 | Optional hybrid — only if evaluation shows it is needed | planned |

See [docs/project-plan.md](docs/project-plan.md) for the authoritative
definitions.

## Non-goals

No web UI, Docker, Kubernetes, databases, vector databases, LangChain,
LlamaIndex, agents, MCP, authentication, PDF processing, chat memory,
streaming, fine-tuning, or production deployment. The full exclusion list is in
the project plan, section 5.

## Corpus disclaimer

All documents under `docs/corpus/` are **fictional and synthetic**. They
describe an invented system ("Cirrus", a building energy-monitoring platform)
created solely to exercise retrieval. They contain no real company
information, no personal information, no credentials, and no secrets.
