import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "engram.db"
DB_PATH.parent.mkdir(exist_ok=True)


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