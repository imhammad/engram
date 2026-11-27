"""The encrypted memory store: one SQLCipher database with sqlite-vec and FTS5.

Everything Engram keeps lives in a single file, data/memory.db, encrypted
with SQLCipher using a 256-bit key that the desktop app keeps in the macOS
Keychain and hands to the engine over stdin (ADR 0008). The file contains
the traces, their FTS5 keyword index and sqlite-vec vectors, activity
sessions, the capture ledger, exclusion rules and settings (ADR 0007).
"""

import hashlib
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import sqlcipher3
import sqlite_vec

from paths import get_data_dir

DB_FILENAME = "memory.db"
EMBEDDING_DIM = 384
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_key: str | None = None
_local = threading.local()
_init_lock = threading.Lock()


class StoreNotConfigured(RuntimeError):
    pass


class WrongKey(RuntimeError):
    """The database exists but this key does not decrypt it."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(text: str) -> str:
    """Hash of the text with whitespace and case normalised, for dedupe."""
    normalised = " ".join(text.split()).lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def read_key_from_stdin() -> str:
    """Read the database key the app writes to our stdin, one hex line.

    The key never travels through argv or the environment, which other
    processes of the same user can read.
    """
    if sys.stdin is None or sys.stdin.isatty():
        sys.exit("The database key must be piped to the engine's stdin. The Engram app does this; "
                 "for development see 'Working on the engine' in the README.")
    line = sys.stdin.readline().strip().lower()
    if not _KEY_PATTERN.match(line):
        sys.exit("The database key on stdin is missing or malformed (expected 64 hex characters).")
    return line


def db_path() -> Path:
    return get_data_dir() / DB_FILENAME


def configure(key_hex: str) -> None:
    """Set the key and make sure the schema is up to date."""
    global _key
    key = key_hex.strip().lower()
    if not _KEY_PATTERN.match(key):
        raise ValueError("database key must be 64 hex characters")
    with _init_lock:
        _key = key
        _local.__dict__.clear()
        try:
            conn = connect()
        except sqlcipher3.DatabaseError as exc:
            _key = None
            raise WrongKey(
                f"{db_path()} could not be decrypted with the key from the Keychain. "
                "Nothing was changed; restore the matching Keychain item or the backup."
            ) from exc
        migrate(conn)


def open_encrypted(path: Path, key_hex: str):
    """Open (or create) an encrypted database file with the sqlite-vec extension loaded."""
    conn = sqlcipher3.connect(str(path), check_same_thread=False)
    # A raw key (x'...') skips SQLCipher's password-based key derivation; the
    # key is already 256 random bits.
    conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlcipher3.Row
    return conn


def connect():
    """A connection for the current thread, opened on first use."""
    if _key is None:
        raise StoreNotConfigured("the memory store has no key yet")
    conn = getattr(_local, "conn", None)
    path = db_path()
    if conn is None or getattr(_local, "path", None) != path:
        conn = open_encrypted(path, _key)
        _local.conn = conn
        _local.path = path
    return conn


def close_thread_connection() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


# --- migrations -----------------------------------------------------------

def _migration_files() -> list[tuple[int, Path]]:
    files = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = re.match(r"^(\d+)_", path.name)
        if match:
            files.append((int(match.group(1)), path))
    return files


def migrate(conn) -> list[int]:
    """Apply any numbered migrations that have not run yet. Returns the versions applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for version, path in _migration_files():
        if version in done:
            continue
        with conn:  # one transaction per migration
            for statement in _split_sql(path.read_text()):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (version, now_iso())
            )
        applied.append(version)
    return applied


def _split_sql(script: str) -> list[str]:
    """Split a migration into statements, keeping trigger bodies intact."""
    statements, current, depth = [], [], 0
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        upper = stripped.upper()
        if upper.startswith("CREATE TRIGGER"):
            depth += 1
        if depth and upper.startswith("END;"):
            depth -= 1
        if not depth and stripped.endswith(";"):
            statements.append("\n".join(current))
            current = []
    if current:
        statements.append("\n".join(current))
    return statements


def schema_version(conn) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return row[0] or 0


# --- settings -------------------------------------------------------------

def get_setting(key: str) -> str | None:
    row = connect().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_setting(key: str, value: str) -> None:
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
