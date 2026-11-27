"""The encrypted memory store: migrations, encryption, legacy import,
hybrid search, time filters, sessions and dedupe."""

import io
import json
import math
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

from conftest import forget_engine_modules


def unit(*pairs: tuple[int, float]) -> list[float]:
    """A 384-dimensional vector with the given components, normalised."""
    v = [0.0] * 384
    for index, value in pairs:
        v[index] = value
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def at(minutes: float) -> str:
    base = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
    return (base + timedelta(minutes=minutes)).isoformat()


# --- migrations -----------------------------------------------------------

def test_migrations_from_empty_create_every_table(fresh_store):
    conn = fresh_store.connect()
    assert fresh_store.schema_version(conn) == 1
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    for table in ("traces", "traces_fts", "trace_vectors", "episodes", "episode_traces", "days",
                  "day_episodes", "activity_sessions", "capture_log", "exclusion_rules", "settings",
                  "schema_migrations"):
        assert table in names, table


def test_migrations_are_applied_once(fresh_store):
    conn = fresh_store.connect()
    assert fresh_store.migrate(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1


# --- encryption -----------------------------------------------------------

def test_database_file_is_encrypted(fresh_store):
    import db

    db.insert_memory("a secret plan for the launch")
    fresh_store.close_thread_connection()
    path = fresh_store.db_path()
    with open(path, "rb") as f:
        header = f.read(16)
    assert header != b"SQLite format 3\x00"
    assert b"secret plan" not in path.read_bytes()
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(path).execute("SELECT * FROM traces").fetchall()


def test_wrong_key_cannot_open_the_database(fresh_store):
    import db

    db.insert_memory("hello")
    fresh_store.close_thread_connection()
    with pytest.raises(Exception, match="not a database"):
        fresh_store.open_encrypted(fresh_store.db_path(), secrets.token_hex(32))
    with pytest.raises(fresh_store.WrongKey):
        fresh_store.configure(secrets.token_hex(32))
    fresh_store.close_thread_connection()
    right = fresh_store.open_encrypted(fresh_store.db_path(), fresh_store.test_key)
    assert right.execute("SELECT COUNT(*) FROM traces").fetchone()[0] == 1


def test_malformed_key_is_rejected(fresh_store):
    with pytest.raises(ValueError):
        fresh_store.configure("not-a-key")


def test_key_comes_from_stdin_and_never_reaches_env_or_logs(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ENGRAM_FAKE_MODELS", "1")
    monkeypatch.setenv("ENGRAM_TOKEN", "t" * 64)
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path / "data"))
    key = secrets.token_hex(32)
    monkeypatch.setattr(sys, "stdin", io.StringIO(key + "\n"))
    forget_engine_modules()
    import main

    try:
        out = capsys.readouterr()
        assert key not in out.out and key not in out.err
        assert all(key not in value for value in os.environ.values())
        assert main.store.connect().execute("SELECT 1").fetchone()[0] == 1
    finally:
        main.store.close_thread_connection()
        forget_engine_modules()


def test_engine_exits_without_a_key_on_stdin(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_FAKE_MODELS", "1")
    monkeypatch.setenv("ENGRAM_TOKEN", "t" * 64)
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
    forget_engine_modules()
    with pytest.raises(SystemExit):
        import main  # noqa: F401
    forget_engine_modules()


# --- legacy import --------------------------------------------------------

def make_legacy_store(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "chroma").mkdir()
    (data_dir / "chroma" / "chroma.sqlite3").write_bytes(b"old vectors")
    conn = sqlite3.connect(data_dir / "engram.db")
    conn.executescript("""
        CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL);
        CREATE TABLE activity_log (id TEXT PRIMARY KEY, window_title TEXT NOT NULL, app_name TEXT NOT NULL, started_at TEXT NOT NULL);
        CREATE TABLE capture_log (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, app_name TEXT NOT NULL DEFAULT '', window_title TEXT NOT NULL DEFAULT '', trigger TEXT NOT NULL, outcome TEXT NOT NULL, reason TEXT, memory_id TEXT);
        CREATE TABLE exclusion_rules (id TEXT PRIMARY KEY, kind TEXT NOT NULL, pattern TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    conn.executemany("INSERT INTO memories VALUES (?, ?, ?, ?)", [
        ("m1", "Plan the EEG seminar for Thursday", "manual", at(0)),
        ("m2", "Quarterly budget review notes", "screen_ocr", at(5)),
        ("m3", "quarterly   BUDGET review notes", "screen_ocr", at(6)),  # duplicate of m2
    ])
    conn.executemany("INSERT INTO activity_log VALUES (?, ?, ?, ?)", [
        ("a1", "Doc", "Pages", at(0)),
        ("a2", "Inbox", "Mail", at(10)),
        ("a3", "Repo", "Chrome", at(200)),  # long gap: app was not running
    ])
    conn.execute("INSERT INTO capture_log VALUES ('c1', ?, 'Chrome', 'Repo', 'auto', 'saved', NULL, 'm2')", (at(5),))
    conn.execute("INSERT INTO exclusion_rules VALUES ('r1', 'app', 'Bank', ?)", (at(0),))
    conn.commit()
    conn.close()


def test_import_from_old_format_db(fresh_store, tmp_path):
    import db
    import legacy_import
    from vector_store import embed_text

    data_dir = tmp_path / "data"
    make_legacy_store(data_dir)
    summary = legacy_import.import_legacy(data_dir, embed_text)

    assert summary["memories_imported"] == 2
    assert summary["memories_skipped_as_duplicates"] == 1
    assert summary["activity_sessions"] == 3
    assert summary["ledger_entries"] == 1 and summary["exclusion_rules"] == 1

    # Old files are moved into the backup folder, not deleted.
    backup = tmp_path / summary["backup_folder"].split("/")[-1]
    assert (backup / "engram.db").is_file()
    assert (backup / "chroma" / "chroma.sqlite3").read_bytes() == b"old vectors"
    assert not (data_dir / "engram.db").exists() and not (data_dir / "chroma").exists()

    memories = {m["id"]: m for m in db.get_all_memories()}
    assert set(memories) == {"m1", "m2"}
    assert memories["m1"]["created_at"] == at(0)

    sessions = sorted(db.get_recent_activity(10), key=lambda s: s["started_at"])
    assert sessions[0]["duration_seconds"] == 600 and sessions[0]["end_reason"] == "switch"
    assert sessions[1]["duration_seconds"] == 0 and sessions[1]["end_reason"] == "imported-gap"
    assert db.get_exclusion_rules()[0]["pattern"] == "Bank"
    assert db.get_capture_log()[0]["memory_id"] == "m2"


def test_import_runs_once(fresh_store, tmp_path):
    import legacy_import
    from vector_store import embed_text

    data_dir = tmp_path / "data"
    make_legacy_store(data_dir)
    assert legacy_import.import_legacy(data_dir, embed_text) is not None
    make_legacy_store(tmp_path / "data")  # even if an old file reappears
    assert legacy_import.import_legacy(data_dir, embed_text) is None


def test_no_import_without_old_store(fresh_store, tmp_path):
    import legacy_import
    from vector_store import embed_text

    assert legacy_import.import_legacy(tmp_path / "data", embed_text) is None


# --- hybrid search --------------------------------------------------------

def test_fusion_finds_what_keyword_and_vector_alone_miss(fresh_store):
    """A matches the words best but means something else; B means the same
    but shares no words; T is second on both and is what the user wants."""
    import db
    from search import hybrid_search, keyword_ranking, vector_ranking

    query = "quarterly budget"
    q = unit((0, 1.0))
    docs = {
        "A": ("quarterly budget quarterly budget template", unit((5, 1.0))),
        "B": ("money plan for the next three months", unit((0, 1.0))),
        "T": ("notes from the quarterly budget meeting with finance", unit((0, 1.0), (1, 0.6))),
        "C": ("lunch order", unit((0, 0.4), (2, 1.0))),
        "D": ("gym schedule", unit((0, 0.3), (3, 1.0))),
        "E": ("weather report", unit((0, 0.2), (4, 1.0))),
    }
    ids = {}
    for name, (text, vec) in docs.items():
        ids[name] = db.insert_trace(text, vec)[0]["id"]
    name_of = {v: k for k, v in ids.items()}

    assert [name_of[i] for i in keyword_ranking(query, 1)] == ["A"]
    assert [name_of[i] for i in vector_ranking(q, 1)] == ["B"]
    assert [name_of[i] for i in hybrid_search(query, q, limit=1)] == ["T"]


def test_search_time_and_app_filters(fresh_store):
    import db
    from search import hybrid_search

    vec = unit((0, 1.0))
    old = db.insert_trace("budget draft one", vec, app_name="Numbers", created_at=at(0))[0]["id"]
    mid = db.insert_trace("budget draft two", unit((0, 1.0), (1, 0.1)), app_name="Pages", created_at=at(60))[0]["id"]
    new = db.insert_trace("budget draft three", unit((0, 1.0), (2, 0.1)), app_name="Numbers", created_at=at(120))[0]["id"]

    assert set(hybrid_search("budget", vec, limit=10)) == {old, mid, new}
    assert set(hybrid_search("budget", vec, limit=10, since=at(30))) == {mid, new}
    assert set(hybrid_search("budget", vec, limit=10, until=at(90))) == {old, mid}
    assert set(hybrid_search("budget", vec, limit=10, since=at(30), until=at(90))) == {mid}
    assert set(hybrid_search("budget", vec, limit=10, app="Numbers")) == {old, new}


def test_search_handles_punctuation_in_queries(fresh_store):
    import db
    from search import hybrid_search

    tid = db.insert_trace("C++ build failed: missing header", unit((0, 1.0)))[0]["id"]
    assert hybrid_search('C++ "build" (failed) AND OR NEAR', unit((0, 1.0)), limit=1) == [tid]


# --- dedupe ---------------------------------------------------------------

def test_identical_traces_are_stored_once(fresh_store):
    import db

    first, created1 = db.insert_trace("Ship the release on Friday", unit((0, 1.0)))
    second, created2 = db.insert_trace("  ship the RELEASE on   friday ", unit((1, 1.0)))
    assert created1 and not created2
    assert second["id"] == first["id"]
    assert len(db.get_all_memories()) == 1


def test_deleting_a_trace_removes_its_vector_and_keywords(fresh_store):
    import db
    from search import keyword_ranking, vector_ranking

    tid = db.insert_trace("unique zebra word", unit((0, 1.0)))[0]["id"]
    assert db.delete_memory(tid)
    assert keyword_ranking("zebra", 5) == []
    assert vector_ranking(unit((0, 1.0)), 5) == []


# --- activity sessions ----------------------------------------------------

def test_sessions_close_on_switch_idle_and_sleep(fresh_store):
    import db

    db.record_switch("Pages", "Report", at(0))
    db.record_switch("Mail", "Inbox", at(1))           # switch closes Pages after 60s
    db.close_open_session("idle", at(1.5))              # idle: last input 30s later
    db.record_switch("Chrome", "Docs", at(10))         # back from idle
    db.close_open_session("sleep", at(12))             # lid closed
    db.record_switch("Chrome", "Docs", at(30))         # wakes up
    db.close_open_session("lock", at(31))

    sessions = sorted(db.get_recent_activity(10), key=lambda s: s["started_at"])
    summary = [(s["app_name"], s["duration_seconds"], s["end_reason"]) for s in sessions]
    assert summary == [
        ("Pages", 60.0, "switch"),
        ("Mail", 30.0, "idle"),
        ("Chrome", 120.0, "sleep"),
        ("Chrome", 60.0, "lock"),
    ]
    # Time per app ignores the idle and sleep gaps.
    totals = {a["app_name"]: a["seconds"] for a in db.time_per_app(at(0), at(60))}
    assert totals == {"Chrome": 180, "Pages": 60, "Mail": 30}


def test_open_session_counts_up_to_now_and_window_is_clipped(fresh_store):
    import db

    db.record_switch("Pages", "Report", at(0))
    totals = db.time_per_app(at(5), at(15))
    assert totals == [{"app_name": "Pages", "seconds": 600}]


def test_stop_without_open_session_is_harmless(fresh_store):
    import db

    assert db.close_open_session("idle") is None


def test_stopwords_do_not_drive_keyword_matches(fresh_store):
    import db
    from search import fts_query, keyword_ranking

    assert fts_query("when is the talk") == '"talk"'
    assert fts_query("the of and") is None
    db.insert_trace("the it is was and the of in on at the is the", unit((0, 1.0)))
    assert keyword_ranking("when is the brain talk", 5) == []
