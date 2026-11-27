import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from migrate_dev_data import migrate  # noqa: E402


def make_source(root: Path) -> Path:
    (root / "chroma").mkdir(parents=True)
    (root / "chroma" / "index.bin").write_bytes(b"vectors")
    (root / "engram.db").write_bytes(b"sqlite")
    return root


def test_copies_db_and_chroma_and_keeps_originals(tmp_path):
    source = make_source(tmp_path / "src")
    dest = tmp_path / "dest"
    assert migrate(source, dest) == 0
    assert (dest / "engram.db").read_bytes() == b"sqlite"
    assert (dest / "chroma" / "index.bin").read_bytes() == b"vectors"
    assert (source / "engram.db").exists()
    assert (source / "chroma" / "index.bin").exists()


def test_refuses_to_overwrite_existing_db(tmp_path):
    source = make_source(tmp_path / "src")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "engram.db").write_bytes(b"newer")
    assert migrate(source, dest) == 1
    assert (dest / "engram.db").read_bytes() == b"newer"


def test_nothing_to_do_without_source_db(tmp_path):
    assert migrate(tmp_path / "missing", tmp_path / "dest") == 0
    assert not (tmp_path / "dest").exists()
