# M3 Retrieval Evaluation — FTS5 Baseline

Sources for this report: `docs/eval/m3-baseline-results.json`,
`docs/eval/golden-queries.jsonl`, the Stage 5 failure analysis, and the existing
M2/M3 documentation. Every number is taken from the recorded results; nothing
was recomputed or altered for this document.

## 1. Objective

M3 measures the lexical retrieval that already exists — FTS5 with BM25 ranking,
OR semantics, and top-k selection over `chunks.jsonl` — without optimizing it.
The milestone freezes an evaluation dataset, defines pure metrics, runs the
current system through a deterministic evaluation runner, and documents what
the measurements show. Retrieval code, the corpus, the index format,
tokenization, query normalization, and ranking behavior are out of scope and
unchanged: M3 answers "how does the current system behave on a labeled set of
queries", not "how can it be improved".

## 2. Evaluation protocol

- **Queries:** 18 frozen queries (`docs/eval/golden-queries.jsonl`), ids
  `q01`–`q18`, covering all 10 corpus documents; each carries gold chunk IDs,
  listed distractors, a rationale, and a difficulty taxonomy.
- **Corpus:** 65 chunks from `chunks.jsonl` (sha256 `81d1a4fb…`), chunk IDs of
  the form `<source_file>:<start>-<end>`.
- **Depth:** k = 5 for every query and every baseline.
- **Metrics:** chunk-level Recall@5, MRR, NDCG@5, plus source-level Recall
  (Section 3).
- **Aggregation:** macro-average over queries — one weight per query, never
  weighted by the number of gold chunks or by the number of documents, and no
  micro-average.
- **Index:** a temporary FTS5 index rebuilt from `chunks.jsonl` with the
  existing `load_records`/`build_index` functions inside an auto-cleaned
  temporary directory. Evaluation never reads or writes the `chunks.db` in the
  working tree.
- **Determinism:** no randomness, network, LLM calls, timestamps, or absolute
  paths appear in any output. Re-running the evaluation — same process or new
  process — reproduces `m3-baseline-results.json` byte for byte (sha256
  `f73c3bce…`). The dataset fingerprint (`5373a322…`) and the corpus
  fingerprint are recorded inside the results file itself.
- **Reproduction:** the runner (`kba/evaluate.py` → `run_evaluation`) accepts
  any retriever with the `retriever(query, k)` contract, and the metrics module
  (`kba/metrics.py`) is pure and I/O-free.

## 3. Metrics

- **Recall@5** — fraction of a query's gold chunks present in the top-5
  ranking. `1` means every gold chunk was retrieved; `0` means none.
- **MRR** — reciprocal rank of the best-ranked gold chunk (`1/rank`, `0` if no
  gold appears), macro-averaged over queries. A query whose first gold sits at
  rank 3 contributes `1/3`.
- **NDCG@5** — normalized discounted cumulative gain with binary gains (a chunk
  scores 1 if it is gold, 0 otherwise) and `IDCG = min(k, |gold|)`. It rewards
  gold chunks placed near the top of the top-5 window.
- **Source Recall** — fraction of the query's gold *source documents*
  represented in the top-5, with the source parsed from the chunk ID
  (`<source>:<start>-<end>`). It separates "found the right document" from
  "found the right section".
- All metrics are computed per query by pure functions and then macro-averaged;
  intermediate values are not rounded.

## 4. Baselines

Both baselines run through the same runner, the same 18 queries, the same
k = 5, the same metric functions, and the same corpus. They differ only in the
retriever callable. The sections describe each one; no general winner is
declared.

### FTS5

The existing M2 retrieval path: `retrieve(query, k)` from `kba/retrieval.py`
unchanged (query normalization, FTS5 tokenizer, OR semantics, BM25 ranking,
top-k). Evaluation rebuilds its index temporarily from `chunks.jsonl` on every
run. This baseline measures the system as it exists today.

### Canonical chunks.jsonl order

A reference retriever that ignores the query: it returns the first k chunks in
the exact file order of `chunks.jsonl`, with `score = 0.0` for every result —
no lexical ranking, no randomness, no call to `retrieve()`. It quantifies how
much a purely positional answer scores under the same metrics.

## 5. Aggregate results

Macro-means over 18 queries at k = 5, straight from
`docs/eval/m3-baseline-results.json`:

| Baseline | Recall@5 | MRR | NDCG@5 | Source Recall |
|---|---|---|---|---|
| FTS5 | 0.6944 | 0.4630 | 0.5278 | 0.8611 |
| Canonical order | 0.0833 | 0.0556 | 0.0600 | 0.0833 |

Descriptive differences: FTS5 is higher than canonical order on all four
aggregate metrics (+0.6111 Recall@5, +0.4074 MRR, +0.4678 NDCG@5, +0.7778
Source Recall). FTS5 retrieved at least one gold chunk in 13 of 18 queries;
canonical order scored non-zero on 2 (q03, q16) only because the golds
`api-rate-limits.md:6-20` and `:22-35` happen to be rows 2–3 of `chunks.jsonl`
— a corpus-position coincidence, not relevance. On q16 canonical order shows
MRR 0.500 and NDCG 0.693 against FTS5's 0.333 and 0.571 (golds at ranks #2/#3
vs #3/#4), with Recall and Source Recall tied at 1.0. These numbers describe the
two systems on this dataset; no general winner is declared.

## 6. Results by taxonomy

FTS5 macro-means per difficulty taxonomy, identical to the Stage 5 analysis:

| Taxonomy | n | Recall@5 | MRR | NDCG@5 | Source Recall |
|---|---|---|---|---|---|
| lexical-easy | 4 | 0.7500 | 0.6250 | 0.6577 | 1.0000 |
| cross-document | 3 | 0.6667 | 0.4444 | 0.4968 | 0.8333 |
| generic-term-pollution | 2 | 1.0000 | 0.6667 | 0.7719 | 1.0000 |
| numeric-near-miss | 2 | 1.0000 | 0.6667 | 0.7500 | 1.0000 |
| distractor-deprecated | 1 | 1.0000 | 0.2500 | 0.5013 | 1.0000 |
| tokenization | 1 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| synonym-gap | 3 | 0.3333 | 0.1111 | 0.1902 | 0.3333 |
| overlapping-topics | 2 | 0.2500 | 0.1250 | 0.1320 | 1.0000 |
| **All queries** | **18** | **0.6944** | **0.4630** | **0.5278** | **0.8611** |

The categories have unequal numbers of queries: `tokenization` and
`distractor-deprecated` have n = 1; `generic-term-pollution`,
`numeric-near-miss`, and `overlapping-topics` have n = 2; `cross-document` and
`synonym-gap` have n = 3; `lexical-easy` has n = 4. Several samples are very
small — the n = 1 and n = 2 rows describe only those queries, and no general
conclusion should be drawn from them. The "All queries" row is the macro-mean
over all 18 queries and matches Section 5.

## 7. Failure analysis

Five queries have Recall@5 = 0: q01, q04, q05, q06, q08. The evidence below
comes from the Stage 5 analysis (scores, token overlaps, and full-ranking
positions extracted read-only from a temporary index; the top-5s are
byte-identical to the results JSON).

**q01 — "How are retries handled?" (overlapping-topics).**
*Lexical mismatch + generic-term pollution.* The gold
`networking-and-retries.md:16-27` shares only the token "are" with the query —
its text says "retried" and "attempts", never "retries" or "handled" — so it
ranks 26. The literal phrase "handled by retries at the uplink" lives in the
distractor `architecture-overview.md:24-34`, which takes rank #1 (score 7.13).
Ranks #2–#5 are preambles matching "how" (present in 3/65 chunks) and "are"
(27/65). Two chunks of the correct document appear in the top-5 but in the
wrong sections, which is why Source Recall is 1.0 while chunk Recall is 0.

**q04 — "How are engineers notified when something fails at night?"
(synonym-gap).**
*Lexical mismatch, structural.* Neither gold chunk shares a single token with
the query (overlap is empty), and both are absent from the full 65-chunk
ranking: under OR semantics FTS5 cannot return them at all. The query's content
words `engineers`, `notified`, `something`, `night` occur in 0/65 chunks; the
corpus says "Page on-call", "pager", "notifies the on-call engineer". The top-5
holds only chunks matching generic words (`how`, `when`, `fails`, `are`, `at`),
and no chunk of the correct document appears (Source Recall 0). This is neither
a ranking failure nor a label issue: per their rationale, the golds' text is
exactly the night-paging answer.

**q05 — "What hardware does the CG-200 gateway use?" (labeled lexical-easy).**
*Lexical mismatch + entity pollution.* None of the three gold chunks repeats
the entity: they begin "Sensor Interfaces", "Local Storage", "Power and
Enclosure". Gold ranks are 59, 20, and absent. The term "hardware" occurs in
4/65 chunks and in no gold; "CG-200" occurs only in preambles and tables of
other documents (the edge preamble, the component table, the credential table —
all listed distractors). The edge preamble takes rank #1 (12.42), keeping
Source Recall at 1.0. The deep gold ranks (not near-misses) indicate a
vocabulary gap rather than a ranking slip, and the golds themselves contain the
requested specifications.

**q06 — "Who do we escalate to when an incident drags on?" (cross-document).**
*Lexical mismatch (morphology) + generic-term pollution, with partial
cross-document retrieval.* The runbook does reach the top-5, but as its
"Known Limitations" section (`troubleshooting-runbook.md:53-56`, rank #1, the
only chunk with a literal "escalate"), while the actual escalation golds say
"Escalation" and rank 11 and 12; the monitoring document is absent from the
top-5 (Source Recall 0.5). The competing tokens are the function words
`when`/`an`/`on`/`to`; "incident" occurs only in the runbook preamble and in no
gold. The golds are inside the ranking but below chunks that share only
function words with the query.

**q08 — "How do employees log in to the system?" (synonym-gap).**
*Lexical mismatch, with a possible gold-label caveat (Section 9).* The gold
`authentication-and-tokens.md:6-15` shares only "the"/"to" with the query and
ranks 41; the correct document first appears at rank #7, outside the window
(Source Recall 0). The corpus contains "employees" 0/65 times and no
"log in"/"sign in"; its single "log" is "audit log" in
`storage-and-retention.md:34-38`, which takes rank #1. The top-5 is generic
matches on "the" (58/65), "to" (28/65), and "in" (23/65).

Where the remaining categories appear: *ranking failure* is not the primary
driver of any zero-recall query — it shows up as degradation elsewhere: the
deprecated chunk above both golds in q10, and a gold one position outside the
cutoff in q15 (Section 8). *Cross-document partial retrieval* appears in q06
(one of two sources present, wrong sections) and q15 (1 of 2 golds retrieved).
*Possible gold-label issue* is flagged only for q08 (Section 9).

## 8. Cross-cutting observations

- **Chunk Recall 0.6944 vs Source Recall 0.8611 (+0.1667).** Four queries
  create the gap: q01 (+1.0), q05 (+1.0), q15 (+0.5), q06 (+0.5) — the
  correct document reaches the top-5 while the exact section or a second gold
  does not. Source Recall is 0 only for q04 and q08.
- **Preambles in 16 of 18 top-5s.** `networking-and-retries.md:1-5` and/or
  `storage-and-retention.md:1-5` occupy at least one top-5 slot in 16 queries
  (all except q03 and q10); their "defines how / what happens when / for how
  long" phrasing matches almost any question.
- **q10 deprecated distractor.** `troubleshooting-runbook.md:42-51`
  ("Deprecated … superseded", which restates current rollback behavior) matches
  7 of the 11 query tokens and scores 13.03 — more than double the best gold
  (5.14). Both golds are still retrieved (#4, #5): Recall 1.0, MRR 0.25.
  BM25 treats the "> DEPRECATED" marker as ordinary text.
- **q15 ranking cutoff.** One gold sits at rank 6, one position outside k = 5,
  below two preambles that each match 8 query tokens: Recall 0.5, MRR 0.25,
  Source Recall 1.0.
- **q18 tokenization.** The alphanumeric token `p95` matches identically in
  query, corpus, and application tokenization; its only corpus occurrence is
  the gold, which ranks #1 (score 11.25). No mismatch was observed in this
  single case.
- **synonym-gap and overlapping-topics are the lowest taxonomies in this
  run.** synonym-gap: mean Recall 0.3333 — q16 succeeds only because it shares
  the literal tokens "requests"/"limit", while q04 and q08 share none.
  overlapping-topics: mean Recall 0.2500 with Source Recall 1.0000 — the right
  document is consistently present while the specific chunks are not.

## 9. Golden dataset limitations

**q05 — dataset metadata vs measurement.** This report does *not* declare the
gold incorrect: each gold chunk contains the hardware specifications described
by its rationale, and the dataset's own notes already record that the entity
"CG-200" appears only in distractors. What the measurement shows is that the
assigned metadata — `difficulty: easy` and taxonomy `lexical-easy` — does not
match the observed behavior (Recall 0; gold ranks 59, 20, absent under FTS5).
That is a dataset-metadata observation, kept separate from the experimental
result: the recorded result stands as measured regardless of the label.

**q08 — possible gold-label issue.** `authentication-and-tokens.md:6-15` is a
*semantic proxy* for login: it is the credential-types table, and neither it
nor any other chunk describes an employee login procedure — the corpus never
uses "log in", and the rationale explicitly treats credentials/tokens as the
documented equivalent of logging in. This is recorded as a **possible**
gold-label issue, not as an unequivocal retrieval failure: under the dataset's
stated synonym-gap intent the query is deliberately phrased outside corpus
vocabulary, but the gold remains a proxy whose correctness cannot be confirmed
from the corpus text alone.

**q18 — tokenization has n = 1.** The `tokenization` category contains
exactly one query, a documented coverage gap (no artificial query was added to
balance the distribution). Its perfect scores (1.0/1.0/1.0/1.0) describe that
single case only; no general conclusion about tokenization behavior should be
drawn from this category.

## 10. What M3 demonstrates

Descriptive findings supported by the recorded results:

- FTS5 retrieved at least one gold chunk in 13 of 18 queries (5 at Recall 0:
  q01, q04, q05, q06, q08).
- Source-level Recall (0.8611) was higher than chunk-level Recall (0.6944):
  the correct document entered the top-5 more often than the exact gold chunks.
- On this dataset, synonym-gap (mean Recall 0.3333) and overlapping-topics
  (0.2500) scored below the other six taxonomies.
- Preamble chunks occupied at least one top-5 slot in 16 of 18 queries.
- Deprecated content obtained rank #1 with score 13.03 in q10, above both
  golds, while both golds were still retrieved.
- The canonical-order baseline scored non-zero only where golds coincide with
  the first rows of `chunks.jsonl` (q03 and q16).
- Every per-query result is reproducible byte for byte across runs and
  processes.

## 11. Limitations

- 18 queries: a small sample, with per-taxonomy cells as small as n = 1.
- Synthetic 10-document corpus of 65 chunks: absolute values are specific to
  this corpus and its wording.
- Taxonomy imbalance (n from 1 to 4 per category).
- Tokenization coverage is n = 1 (q18).
- q08 gold-label uncertainty (possible proxy; Section 9).
- Results may not transfer to other corpora, query distributions, or index
  configurations.
- No latency, throughput, or cost evaluation was performed.
- Only two baselines were measured; no random, vector, hybrid, or reranked
  configurations are included.

## 12. Next-step candidates

Possible areas for future investigation (enumerated only; none implemented,
tested, or endorsed here):

- Query expansion / synonym handling
- Hybrid retrieval
- Reranking
- Metadata-aware filtering
- Deprecated-content handling

## 13. Scope closure

M3 Stage 6 created exactly one file: `docs/eval/m3-baseline-report.md`.

Confirmed:

- No retrieval changes (`kba/retrieval.py`, `kba/indexer.py`, FTS5, tokenizer,
  OR semantics, BM25, top-k).
- No corpus changes (`chunks.jsonl`, `docs/corpus/**`).
- No golden-dataset changes (`docs/eval/golden-queries.jsonl`).
- No metric or runner changes (`kba/metrics.py`, `kba/evaluate.py`).
- No test changes; no new dependencies; no LLM; no vector retrieval; no
  reranking; no random baseline; no CLI.
- No additional files created, no commits made, no push performed.
- All reported results remain byte-identical to
  `docs/eval/m3-baseline-results.json`.

Validation: the full test suite passes (293 tests) and `git diff` shows no
changes to any tracked file.
