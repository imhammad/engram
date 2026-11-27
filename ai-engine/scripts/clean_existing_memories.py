"""Report (and optionally fix) memories saved before the trust baseline.

Memories captured before Phase 2 were stored without redaction or the noise
check. This script runs both over what is in the encrypted store.

By default it is a dry run and changes nothing:

    ai-engine/.venv/bin/python ai-engine/scripts/clean_existing_memories.py

With --apply it first copies memory.db to a timestamped backup folder next
to the data folder, then rewrites redacted memories (and their vectors) and
deletes memories flagged as noise. Typed notes (source "manual") are never
changed. Quit Engram before running --apply.

The database key is read from the macOS Keychain (item dev.engram.app) with
the `security` tool. macOS will ask whether `security` may read it: choose
Allow, not Always Allow, so only the Engram app keeps standing access.
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

APP_SUPPORT = Path.home() / "Library" / "Application Support" / "dev.engram.app"
os.environ.setdefault("ENGRAM_DATA_DIR", str(APP_SUPPORT / "data"))
os.environ.setdefault("ENGRAM_MODEL_DIR", str(APP_SUPPORT / "models"))

import db  # noqa: E402
import store  # noqa: E402
from redact import redact  # noqa: E402
from text_quality import assess_capture  # noqa: E402

MARKERS = ("[email]", "[phone]", "[card]", "[secret]")


def keychain_key() -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", "dev.engram.app", "-a", "database-key", "-w"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit("Could not read the database key from the Keychain. Has Engram been started once?")
    return result.stdout.strip()


def plan() -> list[dict]:
    actions = []
    for m in db.get_all_memories():
        if m["source"] == "manual":
            continue
        content = m["content"]
        redacted = redact(content)
        noise = assess_capture(content)[1] if m["source"] == "screen_ocr" else None
        found = {k.strip("[]"): redacted.count(k) - content.count(k) for k in MARKERS}
        found = {k: n for k, n in found.items() if n > 0}
        if noise:
            actions.append({"id": m["id"], "action": "delete", "reason": noise, "found": found, "created_at": m["created_at"]})
        elif redacted != content:
            actions.append({"id": m["id"], "action": "redact", "found": found, "new": redacted, "created_at": m["created_at"]})
    return actions


def summarise(actions: list[dict], total: int) -> None:
    deletes = [a for a in actions if a["action"] == "delete"]
    redacts = [a for a in actions if a["action"] == "redact"]
    print(f"Memories checked: {total}")
    print(f"Would delete as noise: {len(deletes)}")
    for a in deletes:
        print(f"  {a['id'][:8]}  {a['created_at'][:10]}  {a['reason']}")
    print(f"Would redact: {len(redacts)}")
    for a in redacts:
        kinds = ", ".join(f"{n} {k}" for k, n in a["found"].items())
        print(f"  {a['id'][:8]}  {a['created_at'][:10]}  {kinds}")
    if not actions:
        print("Nothing to change.")


def backup() -> Path:
    data_dir = store.db_path().parent
    dest = data_dir.parent / f"backup-before-clean-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    dest.mkdir()
    conn = store.connect()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(store.db_path(), dest / store.DB_FILENAME)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description="Redact and de-noise existing memories.")
    parser.add_argument("--apply", action="store_true", help="make the changes (after a backup)")
    args = parser.parse_args()

    if not store.db_path().is_file():
        print(f"No database at {store.db_path()}")
        return 1
    store.configure(keychain_key())
    total = len(db.get_all_memories())
    actions = plan()
    print("APPLYING CHANGES.\n" if args.apply else "DRY RUN, nothing will be changed.\n")
    summarise(actions, total)

    if args.apply and actions:
        where = backup()
        print(f"\nBackup written to {where}")
        from vector_store import embed_text

        for a in actions:
            if a["action"] == "delete":
                db.delete_memory(a["id"])
            else:
                db.update_trace_content(a["id"], a["new"], embed_text(a["new"]))
        print("Done.")
    elif actions:
        print("\nRun again with --apply to make these changes (a backup is taken first).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
