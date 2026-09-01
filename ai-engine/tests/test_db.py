import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def db_module(tmp_path, monkeypatch):
    """Give each test a fresh, isolated SQLite database."""
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path))
    # Force a clean import so db.py picks up the env var above
    for mod_name in list(sys.modules):
        if mod_name == "db":
            del sys.modules[mod_name]
    import db as db_module
    db_module.init_db()
    return db_module


def test_insert_memory_returns_expected_fields(db_module):
    result = db_module.insert_memory("test content", source="manual")
    assert result["content"] == "test content"
    assert result["source"] == "manual"
    assert "id" in result
    assert "created_at" in result


def test_insert_memory_defaults_source_to_manual(db_module):
    result = db_module.insert_memory("no source given")
    assert result["source"] == "manual"


def test_get_all_memories_returns_saved_entries(db_module):
    db_module.insert_memory("first memory")
    db_module.insert_memory("second memory")
    all_memories = db_module.get_all_memories()
    assert len(all_memories) == 2
    contents = {m["content"] for m in all_memories}
    assert contents == {"first memory", "second memory"}


def test_get_all_memories_orders_newest_first(db_module):
    first = db_module.insert_memory("older")
    second = db_module.insert_memory("newer")
    all_memories = db_module.get_all_memories()
    assert all_memories[0]["id"] == second["id"]
    assert all_memories[1]["id"] == first["id"]


def test_get_memories_by_ids_returns_matching_only(db_module):
    saved = db_module.insert_memory("findable")
    db_module.insert_memory("not requested")
    result = db_module.get_memories_by_ids([saved["id"]])
    assert len(result) == 1
    assert result[saved["id"]]["content"] == "findable"


def test_get_memories_by_ids_handles_unknown_id(db_module):
    fake_id = str(uuid.uuid4())
    result = db_module.get_memories_by_ids([fake_id])
    assert result == {}


def test_get_memories_by_ids_handles_empty_list(db_module):
    result = db_module.get_memories_by_ids([])
    assert result == {}


def test_log_activity_persists_correctly(db_module):
    result = db_module.log_activity("Some Window", "SomeApp")
    assert result["window_title"] == "Some Window"
    assert result["app_name"] == "SomeApp"


def test_get_stats_counts_by_source(db_module):
    db_module.insert_memory("manual one", source="manual")
    db_module.insert_memory("manual two", source="manual")
    db_module.insert_memory("ocr one", source="screen_ocr")
    stats = db_module.get_stats()
    assert stats["total_memories"] == 3
    assert stats["by_source"]["manual"] == 2
    assert stats["by_source"]["screen_ocr"] == 1

def test_delete_memory_removes_it(db_module):
    saved = db_module.insert_memory("to be deleted")
    result = db_module.delete_memory(saved["id"])
    assert result is True
    assert db_module.get_all_memories() == []


def test_delete_memory_returns_false_for_unknown_id(db_module):
    result = db_module.delete_memory(str(uuid.uuid4()))
    assert result is False


def test_delete_all_memories_removes_everything(db_module):
    db_module.insert_memory("one")
    db_module.insert_memory("two")
    count = db_module.delete_all_memories()
    assert count == 2
    assert db_module.get_all_memories() == []


def test_delete_all_activity_removes_everything(db_module):
    db_module.log_activity("Window A", "AppA")
    db_module.log_activity("Window B", "AppB")
    count = db_module.delete_all_activity()
    assert count == 2