import secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

ENGINE_MODULES = [
    "main", "db", "store", "search", "legacy_import", "vector_store",
    "ocr_capture", "audio_capture", "paths", "fake_models", "exclusions", "recall",
]


def forget_engine_modules() -> None:
    for name in ENGINE_MODULES:
        sys.modules.pop(name, None)


@pytest.fixture
def fresh_store(tmp_path, monkeypatch):
    """A fresh encrypted store in a temporary folder, with stand-in models."""
    monkeypatch.setenv("ENGRAM_FAKE_MODELS", "1")
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ENGRAM_MODEL_DIR", str(tmp_path / "models"))
    forget_engine_modules()
    import store

    key = secrets.token_hex(32)
    store.configure(key)
    store.test_key = key
    yield store
    store.close_thread_connection()
    forget_engine_modules()
