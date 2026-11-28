"""Find (and optionally fix) activity sessions stretched across app downtime.

Before Phase 5, if Engram was quit with Ctrl+C or crashed, the session that
was open stayed open until Engram next started, and was then closed at that
moment: a session can span a whole night. This script lists sessions longer
than --hours that ended by a window switch, which is how those look.

    ai-engine/.venv/bin/python ai-engine/scripts/repair_sessions.py            # dry run
    ai-engine/.venv/bin/python ai-engine/scripts/repair_sessions.py --apply    # cap them at 5 minutes

--apply backs up memory.db first. Quit Engram before running it. The key is
read from the Keychain with the security tool; when macOS asks, choose
Allow, not Always Allow.
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
APP_SUPPORT = Path.home() / "Library" / "Application Support" / "dev.engram.app"
os.environ.setdefault("ENGRAM_DATA_DIR", str(APP_SUPPORT / "data"))

import store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=3.0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    key = subprocess.run(["security", "find-generic-password", "-s", "dev.engram.app", "-a", "database-key", "-w"],
                         capture_output=True, text=True).stdout.strip()
    if not key:
        sys.exit("Could not read the database key from the Keychain.")
    store.configure(key)
    conn = store.connect()
    rows = conn.execute(
        "SELECT id, app_name, started_at, ended_at, duration_seconds FROM activity_sessions "
        "WHERE end_reason = 'switch' AND duration_seconds > ? ORDER BY started_at",
        (args.hours * 3600,),
    ).fetchall()
    print(("APPLYING" if args.apply else "DRY RUN") + f": {len(rows)} session(s) longer than {args.hours:g} h")
    for r in rows:
        print(f"  {r['started_at'][:16]} -> {r['ended_at'][:16]}  {r['app_name']}  {r['duration_seconds'] / 3600:.1f} h")
    if args.apply and rows:
        backup = APP_SUPPORT / f"backup-before-session-repair-{datetime.now():%Y%m%d-%H%M%S}"
        backup.mkdir()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        shutil.copy2(store.db_path(), backup / store.DB_FILENAME)
        with conn:
            for r in rows:
                end = (datetime.fromisoformat(r["started_at"]) + timedelta(minutes=5)).isoformat()
                conn.execute("UPDATE activity_sessions SET ended_at = ?, duration_seconds = 300, end_reason = 'interrupted' WHERE id = ?",
                             (end, r["id"]))
        print(f"Capped. Backup in {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
