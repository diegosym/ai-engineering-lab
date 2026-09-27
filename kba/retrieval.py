"""Application retrieval layer (M2): the ``retrieve(query, k)`` contract.

Application / FTS5 boundary
    The application owns query normalization, tokenization, the conjunction
    policy, k semantics, and score interpretation/presentation. FTS5 owns
    inverted-index lookup, lexical matching, and BM25 ranking. The FTS5
    MATCH expression is *constructed here* from application-extracted
    tokens — user input is never passed through as MATCH syntax — and no
    SQL, SQL text, or SQLite object ever crosses this module's boundary.

Conjunction policy (MVP decision, ADR-001)
    Natural-language queries are evaluated as a **disjunction (OR)** of all
    extracted tokens, ranked by FTS5's BM25. This is an MVP retrieval-policy
    choice — not a claim that OR beats AND. The M2 spike showed FTS5's
    default AND returns zero rows for natural-language queries. M3 will
    evaluate retrieval quality quantitatively and may change this policy.

Score semantics
    FTS5's ``bm25()`` returns *negative* floats (more negative = stronger
    match), which is not intuitive for callers. ``SearchResult.score`` is
    therefore its negation: **higher = better**. Scores are meaningful only
    for ordering the results of a single query — they are NOT comparable
    across queries, corpora, or engines, and are not quality metrics
    (M3 owns evaluation). We do not normalize or rescale them.

Ranking
    FTS5's built-in BM25 with SQLite's default parameters — no custom
    ranking algorithm, no Python-side re-ranking. Equal scores resolve in
    canonical ``chunks.jsonl`` order (deterministic tie-break using the
    internal rowid, which is never exposed).

Identity
    ``SearchResult.id`` is the chunk id — the public stable identity.
    SQLite rowid appears only in internal SQL statements in this module.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .indexer import DEFAULT_DB_PATH

#: Default number of results when the caller does not specify otherwise.
DEFAULT_K = 5

#: Application-level token extraction: unicode letter/digit runs, underscore
#: is a separator (mirrors the index tokenizer's notion of a "word").
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

#: The only SQL in this module: ranked retrieval with a deterministic
#: tie-break (bm25 ascending = best first, then canonical chunk order).
_SELECT_SQL = """
SELECT c.id, c.source_file, c.section, c.text, bm25(chunks_fts)
FROM chunks_fts
JOIN chunks c ON c.rowid = chunks_fts.rowid
WHERE chunks_fts MATCH ?
ORDER BY bm25(chunks_fts) ASC, chunks_fts.rowid ASC
LIMIT ?
"""


class RetrievalError(Exception):
    """The search could not be executed (engine/database failure)."""


class IndexNotBuiltError(RetrievalError):
    """The FTS5 database does not exist yet (run ``python -m kba index``)."""


@dataclass(frozen=True)
class SearchResult:
    """Application-level result: plain data only, no SQLite types."""

    id: str            #: chunk id — public stable identity
    source_file: str
    section: str       #: "" for preamble chunks (M1 convention)
    text: str          #: complete chunk text
    score: float       #: higher = better (negated FTS5 bm25); see module docstring


def tokenize_query(query: str) -> tuple[str, ...]:
    """Apply the application's query policy and extract search tokens.

    Normalization: leading/trailing/inner whitespace is irrelevant (tokens
    are extracted as unicode letter/digit runs). Deliberately NOT done:
    case folding, stemming, stopword removal, synonym expansion, spelling
    correction, and any form of query rewriting.

    Raises:
        TypeError: *query* is not a ``str``.
        ValueError: no searchable tokens remain (empty or punctuation-only
            query) — a usage error, distinct from "no matches".
    """
    if not isinstance(query, str):
        raise TypeError(f"query must be a str, got {type(query).__name__}")
    tokens = tuple(_TOKEN_RE.findall(query))
    if not tokens:
        raise ValueError(
            "query contains no searchable terms "
            "(empty or punctuation-only)"
        )
    return tokens


def _validate_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int):
        raise ValueError(f"k must be an int, got {type(k).__name__}")
    if k <= 0:
        raise ValueError(f"k must be a positive integer, got {k}")


def retrieve(
    query: str, k: int, *, db_path: Path = DEFAULT_DB_PATH
) -> list[SearchResult]:
    """Return up to *k* chunk results for *query*, best first.

    *k* is a maximum (ceiling), not a quota: if fewer than *k* chunks match,
    all matches are returned with no padding. Raises ``ValueError`` for an
    invalid ``k`` or an unsearchable query, ``IndexNotBuiltError`` when the
    database is missing, and ``RetrievalError`` on engine failures. A valid
    query with no matches returns an empty list — a legitimate outcome.
    """
    tokens = tokenize_query(query)
    _validate_k(k)

    db = Path(db_path)
    # Explicit existence check: a bare sqlite3.connect() would silently
    # *create* an empty database instead of reporting a missing index.
    if not db.is_file():
        raise IndexNotBuiltError(
            f"index not found: {db.resolve()} (run: python -m kba index)"
        )

    match_expr = " OR ".join(f'"{t}"' for t in tokens)
    try:
        with closing(sqlite3.connect(db)) as conn:
            rows = conn.execute(_SELECT_SQL, (match_expr, k)).fetchall()
    except sqlite3.Error as exc:
        raise RetrievalError(f"search failed: {exc}") from exc

    return [
        SearchResult(
            id=row[0],
            source_file=row[1],
            section=row[2],
            text=row[3],
            score=-float(row[4]),
        )
        for row in rows
    ]
