"""Report (and optionally fix) existing memories saved before the trust baseline.

Memories captured before Phase 2 were stored without redaction or the noise
check. This script runs both over what is already stored.

By default it is a dry run and changes nothing:

    ai-engine/.venv/bin/python ai-engine/scripts/clean_existing_memories.py

With --apply it first copies engram.db and chroma/ to a timestamped backup
folder next to them, then rewrites redacted memories (and their embeddings)
and deletes memories flagged as noise. Typed notes (source "manual") are
never changed. Quit Engram before running --apply.
"""

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

APP_SUPPORT = Path.home() / "Library" / "Application Support" / "dev.engram.app"
DEFAULT_DATA = APP_SUPPORT / "data"

from redact import redact  # noqa: E402
from text_quality import assess_capture  # noqa: E402

MARKERS = ("[email]", "[phone]", "[card]", "[secret]")


def plan(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, content, source, created_at FROM memories ORDER BY created_at").fetchall()
    conn.close()

    actions = []
    for row in rows:
        if row["source"] == "manual":
            continue
        content = row["content"]
        redacted = redact(content)
        noise = assess_capture(content)[1] if row["source"] == "screen_ocr" else None
        found = {m: redacted.count(m) - content.count(m) for m in MARKERS}
        found = {m.strip("[]"): n for m, n in found.items() if n > 0}
        if noise:
            actions.append({"id": row["id"], "action": "delete", "reason": noise, "found": found, "row": dict(row)})
        elif redacted != content:
            actions.append({"id": row["id"], "action": "redact", "found": found, "new": redacted, "row": dict(row)})
    return actions


def summarise(actions: list[dict], total: int) -> None:
    deletes = [a for a in actions if a["action"] == "delete"]
    redacts = [a for a in actions if a["action"] == "redact"]
    print(f"Memories checked: {total}")
    print(f"Would delete as noise: {len(deletes)}")
    for a in deletes:
        print(f"  {a['id'][:8]}  {a['row']['created_at'][:10]}  {a['reason']}")
    print(f"Would redact: {len(redacts)}")
    for a in redacts:
        kinds = ", ".join(f"{n} {k}" for k, n in a["found"].items())
        print(f"  {a['id'][:8]}  {a['row']['created_at'][:10]}  {kinds}")
    sensitive_in_noise = [a for a in deletes if a["found"]]
    if sensitive_in_noise:
        print(f"(Of the noise memories, {len(sensitive_in_noise)} also contain personal data or secrets.)")
    if not actions:
        print("Nothing to change.")


def backup(data_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = data_dir.parent / f"backup-before-clean-{stamp}"
    dest.mkdir()
    shutil.copy2(data_dir / "engram.db", dest / "engram.db")
    if (data_dir / "chroma").is_dir():
        shutil.copytree(data_dir / "chroma", dest / "chroma")
    return dest


def apply(actions: list[dict], data_dir: Path) -> None:
    os.environ["ENGRAM_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("ENGRAM_MODEL_DIR", str(APP_SUPPORT / "models"))
    import vector_store  # loads the embedding model

    conn = sqlite3.connect(data_dir / "engram.db")
    for a in actions:
        if a["action"] == "delete":
            conn.execute("DELETE FROM memories WHERE id = ?", (a["id"],))
            vector_store.delete_from_vector_store(a["id"])
        else:
            conn.execute("UPDATE memories SET content = ? WHERE id = ?", (a["new"], a["id"]))
            vector_store.delete_from_vector_store(a["id"])
            vector_store.add_to_vector_store(a["id"], a["new"])
    conn.commit()
    conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Redact and de-noise existing memories.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--apply", action="store_true", help="make the changes (after a backup)")
    args = parser.parse_args()

    data_dir = args.data_dir.expanduser()
    db_path = data_dir / "engram.db"
    if not db_path.is_file():
        print(f"No database at {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()

    actions = plan(db_path)
    print("DRY RUN, nothing will be changed.\n" if not args.apply else "APPLYING CHANGES.\n")
    summarise(actions, total)

    if args.apply and actions:
        where = backup(data_dir)
        print(f"\nBackup written to {where}")
        apply(actions, data_dir)
        print("Done.")
    elif actions:
        print("\nRun again with --apply to make these changes (a backup is taken first).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
