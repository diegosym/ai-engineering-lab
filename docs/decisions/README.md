# Architecture Decision Records

Architecturally significant decisions in this project are recorded here as ADRs. This directory is
the single canonical location for decision records (`docs/project-plan.md` §17).

## File naming

`NNN-kebab-title.md` — zero-padded sequence number and a short kebab-case title, e.g.
`001-retrieval-strategy.md`.

## Status lifecycle

`Proposed → Accepted → Superseded by NNN`

- ADRs are immutable once **Accepted**; corrections create a new ADR that supersedes the old one.
- One ADR per architecturally significant decision (changes a boundary, a persistence model, or
  adds a framework or infrastructure). Bug fixes and configuration tweaks do not get ADRs.

## Template (fixed headings)

1. Context
2. Problem
3. Evaluation criteria
4. Alternatives considered
5. Decision
6. Rationale
7. Trade-offs
8. Consequences
9. Status

(ADRs may add evidence appendices or sections — e.g. M2 spike observations — as long as these
headings are present.)

## Rules

- Every ADR lists rejected alternatives with reasons — that is the teaching artifact.
- Evaluation is **qualitative**: no numerical rankings, no scores, no "best"/"winner" language.
  A decision is justified as a **fit to this project's requirements**.
- Retrieval-quality claims belong to measured evaluation (M3+), never to an ADR's selection
  rationale alone.

## Index

| ADR | Title | Status |
|---|---|---|
| [001](001-retrieval-strategy.md) | Retrieval strategy — lexical retrieval engine | **Accepted** (2026-09-24) |
| 002 | Model/provider (M4) | *reserved — not created* |
| 003 | RAG framework (M5) | *reserved — not created* |
| 004 | Vector store (M6) | *reserved — not created* |
| 005 | Hybrid/rerank (M7) | *reserved — not created* |
| 006 | Agent orchestration (M9) | *reserved — not created* |
| 007 | MCP/tools (M10) | *reserved — not created* |
| 008 | Observability (M11) | *reserved — not created* |
