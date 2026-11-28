"""Hybrid search: FTS5 keyword ranking and vector similarity, merged with
reciprocal rank fusion (RRF).

Keyword search finds exact names, numbers and rare words that embeddings
blur; vector search finds paraphrases that share no words with the query.
RRF combines the two rankings without having to calibrate BM25 scores
against cosine distances: each result scores sum(1 / (K + rank)) over the
lists it appears in.
"""

import re

import sqlite_vec

from store import connect

RRF_K = 60


# Words too common to say anything about a match. Without this, a question
# such as "when is the talk" matches any long text containing "is" and "the".
STOPWORDS = frozenset("""
a an and are as at be but by can did do does for from had has have how i if in into is it its
me my no not of on or our so than that the their them then there these they this to was we
were what when where which who why will with would you your about after before
""".split())


def fts_query(text: str) -> str | None:
    """Turn free text into a safe FTS5 query: each word quoted, any may match."""
    words = [w for w in re.findall(r"\w+", text.lower()) if w not in STOPWORDS]
    if not words:
        return None
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))


def _filters(since: str | None, until: str | None, app: str | None) -> tuple[str, list]:
    clauses, params = [], []
    if since:
        clauses.append("t.created_at >= ?")
        params.append(since)
    if until:
        clauses.append("t.created_at < ?")
        params.append(until)
    if app:
        clauses.append("t.app_name = ?")
        params.append(app)
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def keyword_ranking(query: str, limit: int, since=None, until=None, app=None) -> list[str]:
    match = fts_query(query)
    if not match:
        return []
    where, params = _filters(since, until, app)
    rows = connect().execute(
        "SELECT t.id FROM traces_fts JOIN traces t ON t.rowid = traces_fts.rowid "
        f"WHERE traces_fts MATCH ?{where} ORDER BY bm25(traces_fts) LIMIT ?",
        [match, *params, limit],
    ).fetchall()
    return [r[0] for r in rows]


def vector_ranking(embedding: list[float], limit: int, since=None, until=None, app=None) -> list[str]:
    return [i for i, _ in vector_scores(embedding, limit, since, until, app)]


def vector_scores(embedding: list[float], limit: int, since=None, until=None, app=None) -> list[tuple[str, float]]:
    """Nearest traces as (id, cosine distance), closest first."""
    conn = connect()
    total = conn.execute("SELECT COUNT(*) FROM trace_vectors").fetchone()[0]
    if total == 0:
        return []
    where, params = _filters(since, until, app)
    # With filters, look further down the neighbour list so enough survive them.
    k = min(total, limit * (20 if where else 4))
    rows = conn.execute(
        "SELECT t.id, v.distance FROM (SELECT rowid, distance FROM trace_vectors WHERE embedding MATCH ? AND k = ?) v "
        f"JOIN traces t ON t.rowid = v.rowid WHERE 1=1{where} ORDER BY v.distance LIMIT ?",
        [sqlite_vec.serialize_float32(embedding), k, *params, limit],
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def reciprocal_rank_fusion(*rankings: list[str], k: int = RRF_K) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item: scores[item], reverse=True)


def hybrid_search(query: str, embedding: list[float], limit: int = 5, since=None, until=None, app=None) -> list[str]:
    depth = max(limit * 4, 20)
    keyword = keyword_ranking(query, depth, since, until, app)
    vector = vector_ranking(embedding, depth, since, until, app)
    return reciprocal_rank_fusion(keyword, vector)[:limit]


def relevant_search(query: str, embedding: list[float], limit: int = 5, max_distance: float = 0.6,
                    since=None, until=None, app=None) -> list[str]:
    """Hybrid search that only returns traces with real evidence of relevance:
    a keyword match on a meaningful query word, or a vector distance within
    max_distance. Used by recall, where returning nothing is better than
    returning something unrelated (ADR 0012)."""
    depth = max(limit * 4, 20)
    keyword = keyword_ranking(query, depth, since, until, app)
    scored = vector_scores(embedding, depth, since, until, app)
    close = [i for i, d in scored if d <= max_distance]
    fused = reciprocal_rank_fusion(keyword, [i for i, _ in scored])
    allowed = set(keyword) | set(close)
    return [i for i in fused if i in allowed][:limit]
