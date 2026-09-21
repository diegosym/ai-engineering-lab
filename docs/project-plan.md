# Engineering Knowledge Assistant — Project Plan

**Status:** Approved
**Version:** 1.0

## 1. Purpose

Build a small Engineering Knowledge Assistant as a learning project for modern AI application engineering.

The system will eventually allow engineers to ask questions about technical documents and receive answers grounded in those documents with verifiable citations.

The main goals are:
- Understand how RAG works internally.
- Learn modern AI application engineering.
- Learn retrieval evaluation.
- Learn how to use coding agents as engineering collaborators.
- Evolve the system incrementally.

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

## 5. Non-goals

The following are currently out of scope:

- Web UI
- Docker
- Kubernetes
- Databases
- Vector databases
- LangChain
- LlamaIndex
- Agents
- MCP
- Multi-user functionality
- Authentication
- PDF processing
- Chat memory
- Multi-turn conversations
- Streaming
- Fine-tuning
- Background ingestion
- Folder watching
- Query rewriting
- HyDE
- Reranking before evidence justifies it
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

## 11. Technology Decisions

### Language
Python 3.13.

### Environment
Use existing Conda ai-engineering; no other manager.

### CLI
Simple CLI, preferably argparse.

### Storage
Local flat files JSON/JSONL; no DB.

### Retrieval
BM25 first; embeddings later.

### Frameworks
No LangChain/LlamaIndex.

### LLM
Provider undecided; local/free API/multiple providers possible; Mac 8GB; no Ollama before M4.

## 12. Evaluation

Approximately 15–20 golden questions with expected source documents. Measure recall@5. Compare BM25 vs embeddings vs optional hybrid.


## 13. Milestones

M0 Foundation: dedicated repo, minimal metadata, synthetic corpus, docs, existing Conda. No application implementation.

M1 Document Ingestion and Chunking: MD/TXT loaders, heading-aware chunking, overlap, metadata, chunks.jsonl.

M2 BM25 Retrieval: retrieve(query,k), BM25, local index, kba search.

M3 Evaluation: golden questions, expected sources, kba eval, recall@5.

M4 LLM Generation: LLM abstraction, provider, prompt, context, kba ask, citation validation.

M5 Embedding Retrieval: embeddings behind the same retrieve() interface; compare against BM25.

M6 Optional Hybrid: only if evaluation shows BM25 and embeddings are insufficient.

## 14. Engineering Principles

1. Start simple.
2. Measure before optimizing.
3. Prefer explicit code over framework abstraction.
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

## 15. Current Open Decisions

1. LLM provider.
2. Local inference practicality.
3. Real/public documents after MVP.
4. unittest vs pytest.
5. Exact BM25 dependency.
6. Additional metrics beyond recall@5.

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

Current milestone: M0 Foundation.

Next task: create minimal project metadata and synthetic corpus.

Before implementation, the coding agent must read this document and propose exact changes.

The coding agent must wait for approval before modifying files.

