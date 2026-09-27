# M3 Golden Evaluation Dataset

## Purpose

`golden-queries.jsonl` is the frozen evaluation dataset for M3 (Retrieval
Evaluation). It measures the retrieval system that already exists (FTS5, BM25,
OR semantics, top-k over `chunks.jsonl`); it never influences how that system
is built. Each line is one evaluation case: a natural-language query, the
chunks that must be retrieved to answer it, and metadata that explains why the
case is in the dataset.

Stage 1 of M3 ships only this dataset, its documentation, and the tests that
validate it. Metrics, evaluators, baselines, and reports come in later stages.

## Format

One JSON object per line:

| Field | Meaning |
|---|---|
| `id` | Stable identifier, `q01` … `q18` |
| `query` | The literal query string submitted to retrieval |
| `taxonomy` | One of the eight difficulty taxonomies (below) |
| `difficulty` | Subjective expected effort: `easy`, `medium`, `hard` |
| `provenance` | `m2-spike-q1` … `m2-spike-q9` for reused spike queries, `new` for queries written for M3 |
| `relevant_chunk_ids` | Gold labels: 1–3 literal chunk IDs from `chunks.jsonl` |
| `distractor_chunk_ids` | Plausible chunks that must not count as answers |
| `source_docs` | Corpus documents that own the relevant chunks |
| `rationale` | Why each relevant chunk answers the query (evidence-based) |
| `notes` | Ambiguities, judgment calls, and known distractor behavior |

## What "relevant" means

A chunk is **relevant** iff it contains evidence that a correct answer must
include. Relevance is judged against the chunk text, not against shared
keywords: a chunk that repeats the query's words but carries no answer is not
relevant, and a chunk that never repeats the query's words but states the
answer is relevant.

**Relevant vs. distractor:**

- **Relevant** — contributes a fact the complete answer requires. All relevant
  chunks are gold labels and count toward recall.
- **Distractor** (`distractor_chunk_ids`) — plausible for the query (shares
  vocabulary, promises the answer in a preamble, or is explicitly superseded
  content) but does not answer it. Retrieving it wastes a rank slot; it never
  counts as a hit.
- Anything not listed is simply out of scope for that query.

Gold IDs are copied literally from `chunks.jsonl`. Ambiguity is documented in
`notes` instead of being hidden.

## Evaluation level

- **Chunk level is primary**: Recall@5, MRR, and NDCG@5 are computed over
  chunk IDs, because two chunks from the same document can both be required
  (e.g. q03, q14) or one can answer alone (e.g. q12).
- **Source level is secondary**: document-level recall collapses the chunk
  labels per `source_docs` and is reported only as a coarser complement.

## The eight taxonomies

| Taxonomy | n | What the case exercises |
|---|---|---|
| `lexical-easy` | 4 | Query vocabulary appears near-verbatim in the gold chunk |
| `synonym-gap` | 3 | The corpus answers with different words than the query uses |
| `cross-document` | 3 | The full answer requires chunks from two documents |
| `numeric-near-miss` | 2 | The right number exists in a competing scope with similar wording |
| `generic-term-pollution` | 2 | A generic query term appears in most of the corpus |
| `overlapping-topics` | 2 | Several chunks share the topic; only one carries the answer |
| `distractor-deprecated` | 1 | A superseded section competes with current content |
| `tokenization` | 1 | Tokenizer behavior on a discriminative non-word token |

Final distribution: 4 + 3 + 3 + 2 + 2 + 2 + 1 + 1 = **18 queries**.

## Provenance

- **q01–q09** come from the M2 lexical retrieval spike
  (`spike/m2-lexical-retrieval/NOTES.md`, section D) and keep their query text
  verbatim, so dataset results stay comparable with the spike observations
  recorded there.
- **q10–q18** were written for M3 and approved in the dataset review.

## q12 is lexical-easy

q12 was originally labeled `tokenization` (hyphenated `one-wire` and
`CG-200`). The taxonomy was changed to `lexical-easy` because FTS5 splits both
sides of the comparison consistently (`one-wire` → `one` + `wire`,
`CG-200` → `CG` + `200`), so the case cannot isolate a tokenization problem;
it measures ordinary lexical retrieval. The change is recorded in the `notes`
field of q12.

## Known limitation: tokenization has one query

Only q18 carries `taxonomy: tokenization`. No artificial query was added to
balance the distribution: a forced case would be weaker evidence than a single
honest one. Treat tokenization results as anecdotal (n=1).

## Rules

- **Never modify `chunks.jsonl` (or the corpus) to satisfy the dataset.** If a
  gold label seems wrong, fix the dataset's labels or document the ambiguity
  in `notes`; the corpus and the index stay untouched.
- Relevance judgments are evidence-based. Do not invent chunk IDs; every ID in
  this file exists in `chunks.jsonl`.
- The dataset is frozen: changing a query, a label, or a taxonomy is a
  reviewed change, not a refactor.

## Validation

`tests/test_golden_dataset.py` enforces the structural invariants: 18 unique
IDs `q01`–`q18`, required fields, approved taxonomy set, valid difficulty
values, existing gold and distractor IDs, 1–3 relevant chunks per query,
consistent `source_docs`, no duplicate labels, all 10 corpus documents covered,
the exact taxonomy distribution, q12 = `lexical-easy`, q18 = the only
`tokenization` case, spike provenance for q01–q09, and new provenance for
q10–q18.

```bash
python -m pytest tests/test_golden_dataset.py
```
