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


def get_stats() -> dict:
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
    by_source = conn.execute(
        "SELECT source, COUNT(*) as c FROM memories GROUP BY source"
    ).fetchall()
    conn.close()
    return {
        "total_memories": total,
        "by_source": {row["source"]: row["c"] for row in by_source},
    }


def get_recent_activity(limit: int = 15) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM activity_log ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_memory(memory_id: str) -> bool:
    conn = get_connection()
    cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def delete_all_memories() -> int:
    conn = get_connection()
    cursor = conn.execute("DELETE FROM memories")
    conn.commit()
    count = cursor.rowcount
    conn.close()
    return count


def delete_all_activity() -> int:
    conn = get_connection()
    cursor = conn.execute("DELETE FROM activity_log")
    conn.commit()
    count = cursor.rowcount
    conn.close()
    return count