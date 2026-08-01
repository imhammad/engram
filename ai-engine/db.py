import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
import os

DATA_DIR = Path(
    os.environ.get(
        "ENGRAM_DATA_DIR",
        str(Path(__file__).parent / "data"),
    )
)
DATA_DIR.mkdir(exist_ok=True, parents=True)
DB_PATH = DATA_DIR / "engram.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_log (
            id TEXT PRIMARY KEY,
            window_title TEXT NOT NULL,
            app_name TEXT NOT NULL,
            started_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def insert_memory(content: str, source: str = "manual") -> dict:
    memory_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    conn.execute(
        "INSERT INTO memories (id, content, source, created_at) VALUES (?, ?, ?, ?)",
        (memory_id, content, source, created_at),
    )
    conn.commit()
    conn.close()

    return {"id": memory_id, "content": content, "source": source, "created_at": created_at}


def get_all_memories() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM memories ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_memories_by_ids(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    conn = get_connection()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM memories WHERE id IN ({placeholders})", ids
    ).fetchall()
    conn.close()
    return {row["id"]: dict(row) for row in rows}

def log_activity(window_title: str, app_name: str) -> dict:
    entry_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    conn.execute(
        "INSERT INTO activity_log (id, window_title, app_name, started_at) VALUES (?, ?, ?, ?)",
        (entry_id, window_title, app_name, started_at),
    )
    conn.commit()
    conn.close()

    return {"id": entry_id, "window_title": window_title, "app_name": app_name, "started_at": started_at}