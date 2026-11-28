"""Data access for the memory store (see store.py for the connection and schema).

Memories are "traces" in the schema; the API keeps calling them memories.
"""

import uuid
from datetime import datetime, timedelta, timezone

import sqlite_vec

import store
from store import connect, content_hash, now_iso


def _vec(embedding: list[float]) -> bytes:
    return sqlite_vec.serialize_float32(embedding)


def _memory(row) -> dict:
    return {
        "id": row["id"],
        "content": row["content"],
        "source": row["source"],
        "created_at": row["created_at"],
        "app_name": row["app_name"],
        "window_title": row["window_title"],
        "url": row["url"],
        "text_source": row["text_source"],
        "pinned": bool(row["pinned"]),
    }


# --- traces (memories) ----------------------------------------------------

def insert_trace(
    content: str,
    embedding: list[float],
    source: str = "manual",
    app_name: str = "",
    window_title: str = "",
    url: str = "",
    quality: float | None = None,
    created_at: str | None = None,
    trace_id: str | None = None,
    text_source: str = "",
) -> tuple[dict, bool]:
    """Store a trace and its vector. Returns (memory, created).

    If a trace with the same normalised text already exists, nothing is
    stored and the existing memory is returned with created=False.
    """
    conn = connect()
    digest = content_hash(content)
    existing = conn.execute("SELECT * FROM traces WHERE content_hash = ?", (digest,)).fetchone()
    if existing:
        return _memory(existing), False

    trace_id = trace_id or str(uuid.uuid4())
    created = created_at or now_iso()
    with conn:
        cur = conn.execute(
            "INSERT INTO traces (id, content, source, app_name, window_title, url, created_at, quality, content_hash, text_source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trace_id, content, source, app_name, window_title, url, created, quality, digest,
             text_source or {"manual": "typed", "audio_transcription": "audio"}.get(source, "")),
        )
        conn.execute("INSERT INTO trace_vectors (rowid, embedding) VALUES (?, ?)", (cur.lastrowid, _vec(embedding)))
    row = conn.execute("SELECT * FROM traces WHERE id = ?", (trace_id,)).fetchone()
    return _memory(row), True


def insert_memory(content: str, source: str = "manual", embedding: list[float] | None = None) -> dict:
    """Compatibility helper used by tests: embeds with the configured embedder."""
    if embedding is None:
        from vector_store import embed_text
        embedding = embed_text(content)
    return insert_trace(content, embedding, source=source)[0]


def get_all_memories() -> list[dict]:
    rows = connect().execute("SELECT * FROM traces ORDER BY created_at DESC").fetchall()
    return [_memory(r) for r in rows]


def get_memories_by_ids(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = connect().execute(f"SELECT * FROM traces WHERE id IN ({placeholders})", ids).fetchall()
    return {r["id"]: _memory(r) for r in rows}


def delete_memory(memory_id: str) -> bool:
    conn = connect()
    row = conn.execute("SELECT rowid FROM traces WHERE id = ?", (memory_id,)).fetchone()
    if not row:
        return False
    with conn:
        conn.execute("DELETE FROM trace_vectors WHERE rowid = ?", (row[0],))
        conn.execute("DELETE FROM traces WHERE id = ?", (memory_id,))
    return True


def update_trace_content(memory_id: str, content: str, embedding: list[float]) -> bool:
    """Replace a trace's text (for example after redaction) and its vector."""
    conn = connect()
    row = conn.execute("SELECT rowid FROM traces WHERE id = ?", (memory_id,)).fetchone()
    if not row:
        return False
    with conn:
        conn.execute("UPDATE traces SET content = ?, content_hash = ? WHERE id = ?", (content, content_hash(content), memory_id))
        conn.execute("UPDATE trace_vectors SET embedding = ? WHERE rowid = ?", (_vec(embedding), row[0]))
    return True


def delete_all_memories() -> int:
    """Everything remembered: traces and what was built from them."""
    conn = connect()
    count = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
    with conn:
        conn.execute("DELETE FROM trace_vectors")
        conn.execute("DELETE FROM traces")
        conn.execute("DELETE FROM episode_vectors")
        conn.execute("DELETE FROM episodes")
        conn.execute("DELETE FROM days")
        conn.execute("DELETE FROM open_loops")
    return count


def nearest_traces(embedding: list[float], k: int, exclude_id: str | None = None) -> list[dict]:
    """Vector neighbours as [{id, distance}] where distance is cosine distance (1 - cos)."""
    conn = connect()
    total = conn.execute("SELECT COUNT(*) FROM trace_vectors").fetchone()[0]
    if total == 0:
        return []
    fetch = min(total, k + (1 if exclude_id else 0))
    rows = conn.execute(
        "SELECT t.id, v.distance FROM trace_vectors v JOIN traces t ON t.rowid = v.rowid "
        "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
        (_vec(embedding), fetch),
    ).fetchall()
    return [{"id": r[0], "distance": r[1]} for r in rows if r[0] != exclude_id][:k]


def _window_clause(url: str) -> str:
    # A page is identified by its URL when there is one, otherwise by its title.
    return "url = ?" if url else "window_title = ?"


def last_capture_of_window(app_name: str, window_title: str, url: str) -> dict | None:
    """The most recent captured trace from the same window (app plus URL or title)."""
    row = connect().execute(
        f"SELECT * FROM traces WHERE source = 'screen_ocr' AND app_name = ? AND {_window_clause(url)} "
        "ORDER BY created_at DESC LIMIT 1",
        (app_name, url or window_title),
    ).fetchone()
    return dict(row) if row else None


def recent_captures_of_other_windows(app_name: str, window_title: str, url: str, limit: int = 5) -> list[str]:
    """Text of the app's latest captures from other windows, for spotting UI chrome."""
    rows = connect().execute(
        f"SELECT content FROM traces WHERE source = 'screen_ocr' AND app_name = ? AND NOT ({_window_clause(url)}) "
        "ORDER BY created_at DESC LIMIT ?",
        (app_name, url or window_title, limit),
    ).fetchall()
    return [r[0] for r in rows]


def get_stats() -> dict:
    conn = connect()
    total = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
    rows = conn.execute("SELECT source, COUNT(*) FROM traces GROUP BY source").fetchall()
    return {"total_memories": total, "by_source": {r[0]: r[1] for r in rows}}


# --- activity sessions ----------------------------------------------------
# The shell reports window switches and the moments activity stops (idle,
# sleep, screen lock, quit). A session runs from one switch to the next
# switch or stop. See ADR 0007.

def _seconds_between(start: str, end: str) -> float:
    return max((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 0.0)


def close_open_session(reason: str, ended_at: str | None = None) -> dict | None:
    """End the open session, if any, at ended_at (default now)."""
    conn = connect()
    row = conn.execute(
        "SELECT * FROM activity_sessions WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    end = ended_at or now_iso()
    if end < row["started_at"]:
        end = row["started_at"]
    duration = _seconds_between(row["started_at"], end)
    with conn:
        conn.execute(
            "UPDATE activity_sessions SET ended_at = ?, duration_seconds = ?, end_reason = ? WHERE id = ?",
            (end, duration, reason, row["id"]),
        )
        # Any older sessions left open (for example after a crash) are closed at their start.
        conn.execute(
            "UPDATE activity_sessions SET ended_at = started_at, duration_seconds = 0, end_reason = 'abandoned' "
            "WHERE ended_at IS NULL"
        )
    return {**dict(row), "ended_at": end, "duration_seconds": duration, "end_reason": reason}


# A session still open when the engine starts was cut off by a crash or a
# forced quit; the app stopped reporting at some unknown point. It is closed
# at most this long after it began, rather than stretching across the hours
# Engram was not running.
INTERRUPTED_SESSION_MAX_SECONDS = 5 * 60


def close_interrupted_sessions() -> int:
    conn = connect()
    rows = conn.execute("SELECT id, started_at FROM activity_sessions WHERE ended_at IS NULL").fetchall()
    now = now_iso()
    with conn:
        for r in rows:
            cap = (datetime.fromisoformat(r["started_at"]) + timedelta(seconds=INTERRUPTED_SESSION_MAX_SECONDS)).isoformat()
            end = min(cap, now)
            conn.execute(
                "UPDATE activity_sessions SET ended_at = ?, duration_seconds = ?, end_reason = 'interrupted' WHERE id = ?",
                (end, _seconds_between(r["started_at"], end), r["id"]),
            )
    return len(rows)


def record_switch(app_name: str, window_title: str, at: str | None = None) -> dict:
    """Close the current session and open one for the new window."""
    start = at or now_iso()
    close_open_session("switch", start)
    session = {
        "id": str(uuid.uuid4()),
        "app_name": app_name,
        "window_title": window_title,
        "started_at": start,
    }
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO activity_sessions (id, app_name, window_title, started_at) VALUES (:id, :app_name, :window_title, :started_at)",
            session,
        )
    return session


def insert_session(app_name: str, window_title: str, started_at: str, ended_at: str, end_reason: str) -> None:
    """Store a finished session as is (used when importing old activity)."""
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO activity_sessions (id, app_name, window_title, started_at, ended_at, duration_seconds, end_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), app_name, window_title, started_at, ended_at, _seconds_between(started_at, ended_at), end_reason),
        )


def get_recent_activity(limit: int = 15) -> list[dict]:
    rows = connect().execute(
        "SELECT * FROM activity_sessions ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def time_per_app(since: str, until: str | None = None, limit: int = 8) -> list[dict]:
    """Seconds spent per app between since and until, counting the open session up to now."""
    end = until or now_iso()
    rows = connect().execute(
        "SELECT app_name, started_at, COALESCE(ended_at, ?) AS ended_at FROM activity_sessions "
        "WHERE COALESCE(ended_at, ?) > ? AND started_at < ?",
        (end, end, since, end),
    ).fetchall()
    from exclusions import is_system_process

    totals: dict[str, float] = {}
    for r in rows:
        if is_system_process(r["app_name"]):
            continue
        start = max(r["started_at"], since)
        stop = min(r["ended_at"], end)
        totals[r["app_name"]] = totals.get(r["app_name"], 0.0) + _seconds_between(start, stop)
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"app_name": app, "seconds": round(sec)} for app, sec in ranked if sec >= 1]


def delete_all_activity() -> int:
    conn = connect()
    count = conn.execute("SELECT COUNT(*) FROM activity_sessions").fetchone()[0]
    with conn:
        conn.execute("DELETE FROM activity_sessions")
    return count


# --- capture ledger -------------------------------------------------------

def log_capture(
    trigger: str,
    outcome: str,
    app_name: str = "",
    window_title: str = "",
    reason: str | None = None,
    memory_id: str | None = None,
    created_at: str | None = None,
    text_source: str = "",
    url: str = "",
) -> dict:
    entry = {
        "text_source": text_source,
        "url": url,
        "id": str(uuid.uuid4()),
        "created_at": created_at or now_iso(),
        "app_name": app_name,
        "window_title": window_title,
        "trigger": trigger,
        "outcome": outcome,
        "reason": reason,
        "memory_id": memory_id,
    }
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO capture_log (id, created_at, app_name, window_title, trigger, outcome, reason, memory_id, text_source, url) "
            "VALUES (:id, :created_at, :app_name, :window_title, :trigger, :outcome, :reason, :memory_id, :text_source, :url)",
            entry,
        )
    return entry


def get_capture_log(limit: int = 200) -> list[dict]:
    rows = connect().execute("SELECT * FROM capture_log ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def delete_capture_log_entry(entry_id: str) -> bool:
    conn = connect()
    with conn:
        cur = conn.execute("DELETE FROM capture_log WHERE id = ?", (entry_id,))
    return cur.rowcount > 0


def delete_all_capture_log() -> int:
    conn = connect()
    with conn:
        cur = conn.execute("DELETE FROM capture_log")
    return cur.rowcount


# --- user exclusion rules -------------------------------------------------

def add_exclusion_rule(kind: str, pattern: str, created_at: str | None = None, rule_id: str | None = None) -> dict:
    rule = {"id": rule_id or str(uuid.uuid4()), "kind": kind, "pattern": pattern, "created_at": created_at or now_iso()}
    conn = connect()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO exclusion_rules (id, kind, pattern, created_at) VALUES (:id, :kind, :pattern, :created_at)",
            rule,
        )
    return rule


def get_exclusion_rules() -> list[dict]:
    rows = connect().execute("SELECT * FROM exclusion_rules ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def delete_exclusion_rule(rule_id: str) -> bool:
    conn = connect()
    with conn:
        cur = conn.execute("DELETE FROM exclusion_rules WHERE id = ?", (rule_id,))
    return cur.rowcount > 0


def init_db() -> None:
    """Kept for callers of the old API; the schema is applied by store.configure()."""
    store.connect()


# --- recall helpers -------------------------------------------------------

def known_app_names() -> list[str]:
    """Every app that appears in activity or memories, for matching names in questions."""
    conn = connect()
    names = {r[0] for r in conn.execute("SELECT DISTINCT app_name FROM activity_sessions")}
    names |= {r[0] for r in conn.execute("SELECT DISTINCT app_name FROM traces WHERE app_name != ''")}
    return sorted(n for n in names if n)


def sessions_between(since: str, until: str, app_name: str | None = None) -> list[dict]:
    """Sessions overlapping [since, until), oldest first, open sessions counted to until."""
    params: list = [until, until, since, until]
    app_clause = ""
    if app_name:
        app_clause = " AND app_name = ?"
        params.append(app_name)
    rows = connect().execute(
        "SELECT *, COALESCE(ended_at, ?) AS effective_end FROM activity_sessions "
        f"WHERE COALESCE(ended_at, ?) > ? AND started_at < ?{app_clause} ORDER BY started_at",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def traces_between(since: str, until: str, limit: int = 40) -> list[dict]:
    rows = connect().execute(
        "SELECT * FROM traces WHERE created_at >= ? AND created_at < ? ORDER BY created_at",
        (since, until),
    ).fetchall()
    return [_memory(r) for r in rows][:limit] if len(rows) <= limit else [_memory(r) for r in rows[-limit:]]


def touch_recalled(ids: list[str]) -> None:
    """Remember that these traces were used in an answer (for forgetting, Phase 6)."""
    if not ids:
        return
    conn = connect()
    with conn:
        conn.executemany("UPDATE traces SET last_recalled_at = ? WHERE id = ?", [(now_iso(), i) for i in ids])


# --- recall history -------------------------------------------------------

def add_recall(question: str, answer: str, route: str, sources: list[dict]) -> dict:
    import json as _json

    entry = {"id": str(uuid.uuid4()), "created_at": now_iso(), "question": question, "answer": answer,
             "route": route, "sources": _json.dumps(sources)}
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO recall_history (id, created_at, question, answer, route, sources) "
            "VALUES (:id, :created_at, :question, :answer, :route, :sources)", entry)
    return entry


def get_recall_history(limit: int = 30) -> list[dict]:
    import json as _json

    rows = connect().execute("SELECT * FROM recall_history ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "sources": _json.loads(r["sources"] or "[]")} for r in rows]


def clear_recall_history() -> int:
    conn = connect()
    with conn:
        cur = conn.execute("DELETE FROM recall_history")
    return cur.rowcount


# --- consolidation ----------------------------------------------------------

def day_exists(day: str) -> bool:
    return connect().execute("SELECT 1 FROM days WHERE date = ?", (day,)).fetchone() is not None


def earliest_activity_or_trace() -> str | None:
    conn = connect()
    a = conn.execute("SELECT MIN(started_at) FROM activity_sessions").fetchone()[0]
    t = conn.execute("SELECT MIN(created_at) FROM traces").fetchone()[0]
    return min(x for x in (a, t) if x) if (a or t) else None


def has_activity_or_traces(since: str, until: str) -> bool:
    conn = connect()
    if conn.execute("SELECT 1 FROM traces WHERE created_at >= ? AND created_at < ? LIMIT 1", (since, until)).fetchone():
        return True
    return conn.execute("SELECT 1 FROM activity_sessions WHERE started_at >= ? AND started_at < ? LIMIT 1",
                        (since, until)).fetchone() is not None


def save_consolidated_day(day: str, episodes: list[dict], summary: str, stats: dict, embeddings: list[list[float]]) -> None:
    """Replace the day's episodes and summary in one transaction."""
    import json as _json

    conn = connect()
    with conn:
        old = [r[0] for r in conn.execute("SELECT rowid FROM episodes WHERE day = ?", (day,))]
        for rowid in old:
            conn.execute("DELETE FROM episode_vectors WHERE rowid = ?", (rowid,))
        conn.execute("DELETE FROM episodes WHERE day = ?", (day,))
        conn.execute("DELETE FROM days WHERE date = ?", (day,))
        conn.execute("INSERT INTO days (date, summary, created_at, stats) VALUES (?, ?, ?, ?)",
                     (day, summary, now_iso(), _json.dumps(stats)))
        for n, (e, vec) in enumerate(zip(episodes, embeddings), 1):
            cur = conn.execute(
                "INSERT INTO episodes (id, title, summary, started_at, ended_at, created_at, day, apps, focused_seconds) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (e["id"], e["title"], e["summary"], e["started_at"], e["ended_at"], now_iso(), day,
                 _json.dumps(e["apps"]), e["focused_seconds"]))
            conn.execute("INSERT INTO episode_vectors (rowid, embedding) VALUES (?, ?)", (cur.lastrowid, _vec(vec)))
            conn.execute("INSERT INTO day_episodes (date, episode_id, n) VALUES (?, ?, ?)", (day, e["id"], n))
            for tid in e["trace_ids"]:
                conn.execute("INSERT OR IGNORE INTO episode_traces (episode_id, trace_id) VALUES (?, ?)", (e["id"], tid))
            for s in e["sources"]:
                conn.execute(
                    "INSERT INTO episode_sources (episode_id, n, trace_id, app_name, window_title, url, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (e["id"], s["n"], s["trace_id"], s["app_name"], s["window_title"], s["url"], s["created_at"]))


def get_day(day: str) -> dict | None:
    import json as _json

    conn = connect()
    row = conn.execute("SELECT * FROM days WHERE date = ?", (day,)).fetchone()
    if not row:
        return None
    eps = conn.execute(
        "SELECT e.* FROM day_episodes d JOIN episodes e ON e.id = d.episode_id WHERE d.date = ? ORDER BY d.n", (day,)
    ).fetchall()
    return {"date": day, "summary": row["summary"], "stats": _json.loads(row["stats"] or "{}"),
            "episodes": [episode_dict(e) for e in eps]}


def episode_dict(row) -> dict:
    import json as _json

    sources = connect().execute(
        "SELECT * FROM episode_sources WHERE episode_id = ? ORDER BY n", (row["id"],)).fetchall()
    return {"id": row["id"], "title": row["title"], "summary": row["summary"], "started_at": row["started_at"],
            "ended_at": row["ended_at"], "day": row["day"], "apps": _json.loads(row["apps"] or "[]"),
            "focused_seconds": row["focused_seconds"], "sources": [dict(s) for s in sources]}


def get_episodes_by_ids(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = connect().execute(f"SELECT * FROM episodes WHERE id IN ({placeholders})", ids).fetchall()
    return {r["id"]: episode_dict(r) for r in rows}


def episode_search(query_words: set[str], embedding: list[float], since: str | None, until: str | None,
                   limit: int = 2, max_distance: float = 0.55) -> list[str]:
    """Episodes whose title or summary shares a meaningful word with the
    question, or whose vector is close, within the period."""
    conn = connect()
    clauses, params = [], []
    if since:
        clauses.append("e.ended_at >= ?")
        params.append(since)
    if until:
        clauses.append("e.started_at < ?")
        params.append(until)
    where = (" AND " + " AND ".join(clauses)) if clauses else ""
    total = conn.execute("SELECT COUNT(*) FROM episode_vectors").fetchone()[0]
    found: list[str] = []
    if total:
        rows = conn.execute(
            "SELECT e.id, v.distance FROM (SELECT rowid, distance FROM episode_vectors WHERE embedding MATCH ? AND k = ?) v "
            f"JOIN episodes e ON e.rowid = v.rowid WHERE 1=1{where} ORDER BY v.distance",
            [_vec(embedding), min(total, 20), *params]).fetchall()
        found = [r[0] for r in rows if r[1] <= max_distance]
    if query_words:
        for r in conn.execute(f"SELECT e.id, e.title, e.summary FROM episodes e WHERE 1=1{where}", params):
            text = (r["title"] + " " + r["summary"]).lower()
            if any(w in text for w in query_words) and r["id"] not in found:
                found.append(r["id"])
    return found[:limit]


def mark_episode_sources_faded(trace_ids: list[str]) -> None:
    if not trace_ids:
        return
    conn = connect()
    with conn:
        conn.executemany("UPDATE episode_sources SET faded = 1 WHERE trace_id = ?", [(t,) for t in trace_ids])


# --- forgetting -------------------------------------------------------------

_FADE_WHERE = (
    "t.created_at < :cutoff AND t.pinned = 0 "
    "AND (t.last_recalled_at IS NULL OR t.last_recalled_at < :cutoff) "
    "AND EXISTS (SELECT 1 FROM episode_traces et WHERE et.trace_id = t.id)"
)


def fade_candidates(cutoff: str) -> list[str]:
    """Traces old enough to fade: not pinned, not recalled lately, and already
    part of a consolidated episode."""
    return [r[0] for r in connect().execute(f"SELECT t.id FROM traces t WHERE {_FADE_WHERE}", {"cutoff": cutoff})]


def fade_counts(cutoff: str) -> dict:
    conn = connect()
    would = conn.execute(f"SELECT COUNT(*) FROM traces t WHERE {_FADE_WHERE}", {"cutoff": cutoff}).fetchone()[0]
    pinned = conn.execute("SELECT COUNT(*) FROM traces WHERE created_at < ? AND pinned = 1", (cutoff,)).fetchone()[0]
    recalled = conn.execute(
        "SELECT COUNT(*) FROM traces WHERE created_at < ? AND pinned = 0 AND last_recalled_at >= ?", (cutoff, cutoff)
    ).fetchone()[0]
    return {"would_fade": would, "kept_by_pin": pinned, "kept_by_recall": recalled}


def set_pinned(memory_id: str, pinned: bool) -> bool:
    conn = connect()
    with conn:
        cur = conn.execute("UPDATE traces SET pinned = ? WHERE id = ?", (1 if pinned else 0, memory_id))
    return cur.rowcount > 0


# --- open loops -------------------------------------------------------------

def open_loop_exists(text_hash: str) -> bool:
    return connect().execute("SELECT 1 FROM open_loops WHERE text_hash = ?", (text_hash,)).fetchone() is not None


def add_open_loop(trace_id: str, text: str, text_hash: str, app_name: str, created_at: str) -> None:
    conn = connect()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO open_loops (id, trace_id, text, text_hash, app_name, created_at, status, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'open', ?)",
            (str(uuid.uuid4()), trace_id, text, text_hash, app_name, created_at, now_iso()))


def get_open_loops(status: str = "open", limit: int = 50) -> list[dict]:
    rows = connect().execute(
        "SELECT * FROM open_loops WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit)).fetchall()
    return [dict(r) for r in rows]


def set_open_loop_status(loop_id: str, status: str) -> bool:
    conn = connect()
    with conn:
        cur = conn.execute("UPDATE open_loops SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), loop_id))
    return cur.rowcount > 0


def consolidated_days() -> list[str]:
    return [r[0] for r in connect().execute("SELECT date FROM days ORDER BY date")]
