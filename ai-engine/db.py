"""Data access for the memory store (see store.py for the connection and schema).

Memories are "traces" in the schema; the API keeps calling them memories.
"""

import uuid
from datetime import datetime, timezone

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
    conn = connect()
    count = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
    with conn:
        conn.execute("DELETE FROM trace_vectors")
        conn.execute("DELETE FROM traces")
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
