"""Copy development data from ai-engine/data into the app's data directory.

Before Phase 1 the engine stored engram.db and the Chroma index in
ai-engine/data inside the repository. The desktop app now keeps them in
~/Library/Application Support/dev.engram.app/data. Run this once to carry
existing memories across:

    ai-engine/.venv/bin/python ai-engine/scripts/migrate_dev_data.py

It only copies, never moves or deletes, and it refuses to run if the
destination already has an engram.db, so it cannot overwrite newer data.
"""

import argparse
import shutil
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ENGINE_DIR / "data"
DEFAULT_DEST = Path.home() / "Library" / "Application Support" / "dev.engram.app" / "data"


def migrate(source: Path, dest: Path) -> int:
    source_db = source / "engram.db"
    if not source_db.is_file():
        print(f"Nothing to migrate: {source_db} does not exist.")
        return 0
    if (dest / "engram.db").exists():
        print(f"{dest / 'engram.db'} already exists. Not copying, to avoid overwriting it.")
        return 1

    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_db, dest / "engram.db")
    print(f"Copied {source_db} -> {dest / 'engram.db'}")

    source_chroma = source / "chroma"
    if source_chroma.is_dir():
        if (dest / "chroma").exists():
            print(f"{dest / 'chroma'} already exists. Leaving it in place.")
        else:
            shutil.copytree(source_chroma, dest / "chroma")
            print(f"Copied {source_chroma} -> {dest / 'chroma'}")
    print("Done. The originals in the repository were not changed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy dev data into the app data directory.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args()
    return migrate(args.source.expanduser(), args.dest.expanduser())


if __name__ == "__main__":
    sys.exit(main())
