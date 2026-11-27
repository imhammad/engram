"""One-time import from the pre-Phase-3 storage into the encrypted store.

Before Phase 3, data/engram.db was a plain SQLite file and vectors lived in
a ChromaDB folder, data/chroma/. On the first start with the new store this
module moves both into a timestamped backup folder next to data/ (nothing is
deleted), then imports memories, activity, the capture ledger and exclusion
rules into memory.db, re-embedding every memory from its text. It records
completion in the settings table, so it runs once.
"""

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

import db
import store

DONE_KEY = "legacy_import_completed_at"
SUMMARY_KEY = "legacy_import_summary"
# The old tracker only logged switches while the app ran, so a long gap
# between two switch events usually means Engram was not running. Gaps
# longer than this are imported as zero-length sessions rather than as hours
# spent in one window.
MAX_IMPORTED_SESSION_SECONDS = 30 * 60


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _is_plain_sqlite(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(16) == b"SQLite format 3\x00"


def import_legacy(data_dir: Path, embed: Callable[[str], list[float]]) -> dict | None:
    """Import the old store if it is there and has not been imported. Returns a summary."""
    old_db = data_dir / "engram.db"
    if store.get_setting(DONE_KEY) or not old_db.is_file() or not _is_plain_sqlite(old_db):
        return None

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = data_dir.parent / f"backup-before-phase3-{stamp}"
    backup.mkdir(parents=True)

    # Read everything first, from the original, before moving anything.
    src = sqlite3.connect(old_db)
    src.row_factory = sqlite3.Row
    memories = [dict(r) for r in src.execute("SELECT * FROM memories ORDER BY created_at")] if _table_exists(src, "memories") else []
    activity = [dict(r) for r in src.execute("SELECT * FROM activity_log ORDER BY started_at")] if _table_exists(src, "activity_log") else []
    ledger = [dict(r) for r in src.execute("SELECT * FROM capture_log ORDER BY created_at")] if _table_exists(src, "capture_log") else []
    rules = [dict(r) for r in src.execute("SELECT * FROM exclusion_rules")] if _table_exists(src, "exclusion_rules") else []
    src.close()

    # Move (not delete) the old files into the backup folder.
    for name in ("engram.db", "engram.db-wal", "engram.db-shm", "chroma"):
        path = data_dir / name
        if path.exists():
            shutil.move(str(path), str(backup / name))

    imported = duplicates = 0
    for m in memories:
        _, created = db.insert_trace(
            m["content"], embed(m["content"]), source=m.get("source") or "manual",
            created_at=m.get("created_at"), trace_id=m.get("id"),
        )
        imported += created
        duplicates += not created

    sessions = 0
    for i, event in enumerate(activity):
        start = event["started_at"]
        if i + 1 < len(activity):
            gap = (datetime.fromisoformat(activity[i + 1]["started_at"]) - datetime.fromisoformat(start)).total_seconds()
            end, reason = (activity[i + 1]["started_at"], "switch") if 0 <= gap <= MAX_IMPORTED_SESSION_SECONDS else (start, "imported-gap")
        else:
            end, reason = start, "imported-gap"
        db.insert_session(event["app_name"], event.get("window_title") or "", start, end, reason)
        sessions += 1

    for e in ledger:
        db.log_capture(e["trigger"], e["outcome"], e.get("app_name") or "", e.get("window_title") or "",
                       e.get("reason"), e.get("memory_id"), created_at=e["created_at"])
    for r in rules:
        db.add_exclusion_rule(r["kind"], r["pattern"], created_at=r.get("created_at"), rule_id=r.get("id"))

    summary = {
        "backup_folder": str(backup),
        "memories_imported": imported,
        "memories_skipped_as_duplicates": duplicates,
        "activity_sessions": sessions,
        "ledger_entries": len(ledger),
        "exclusion_rules": len(rules),
    }
    store.set_setting(SUMMARY_KEY, json.dumps(summary))
    store.set_setting(DONE_KEY, store.now_iso())
    print(f"Imported the previous store: {json.dumps(summary)}")
    return summary
