import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import paths  # noqa: E402


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("ENGRAM_DATA_DIR", "ENGRAM_MODEL_DIR", "TESSERACT_CMD"):
        monkeypatch.delenv(var, raising=False)


def make_executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


# --- offline mode ---------------------------------------------------------

def test_importing_paths_enables_hugging_face_offline_mode():
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"


# --- data and model directories -------------------------------------------

def test_data_dir_uses_env_override_and_creates_it(tmp_path, monkeypatch):
    target = tmp_path / "app-support" / "data"
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(target))
    assert paths.get_data_dir() == target
    assert target.is_dir()


def test_data_dir_falls_back_to_engine_folder():
    assert paths.get_data_dir() == paths.ENGINE_DIR / "data"


def test_model_dir_uses_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_MODEL_DIR", str(tmp_path))
    assert paths.get_model_dir() == tmp_path


def test_model_dir_falls_back_to_engine_folder():
    assert paths.get_model_dir() == paths.ENGINE_DIR / "models"


def test_model_paths_resolve_inside_model_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_MODEL_DIR", str(tmp_path))
    (tmp_path / paths.LLM_FILENAME).write_bytes(b"")
    (tmp_path / paths.EMBEDDER_DIRNAME).mkdir()
    (tmp_path / paths.WHISPER_DIRNAME).mkdir()
    assert paths.llm_path() == tmp_path / paths.LLM_FILENAME
    assert paths.embedder_path() == tmp_path / paths.EMBEDDER_DIRNAME
    assert paths.whisper_path() == tmp_path / paths.WHISPER_DIRNAME


def test_missing_model_raises_with_fetch_instructions(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_MODEL_DIR", str(tmp_path))
    with pytest.raises(paths.MissingModelError, match="fetch_models.py"):
        paths.embedder_path()


# --- tesseract lookup -----------------------------------------------------

def test_tesseract_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("TESSERACT_CMD", "/custom/tesseract")
    monkeypatch.setattr(paths.shutil, "which", lambda _: "/on/path/tesseract")
    assert paths.find_tesseract_cmd() == "/custom/tesseract"


def test_tesseract_found_on_path(monkeypatch):
    monkeypatch.setattr(paths.shutil, "which", lambda _: "/on/path/tesseract")
    assert paths.find_tesseract_cmd() == "/on/path/tesseract"


def test_tesseract_falls_back_to_homebrew_location(tmp_path, monkeypatch):
    brew = make_executable(tmp_path / "tesseract")
    monkeypatch.setattr(paths.shutil, "which", lambda _: None)
    monkeypatch.setattr(paths, "HOMEBREW_TESSERACT_PATHS", (str(tmp_path / "missing"), str(brew)))
    assert paths.find_tesseract_cmd() == str(brew)


def test_tesseract_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.shutil, "which", lambda _: None)
    monkeypatch.setattr(paths, "HOMEBREW_TESSERACT_PATHS", (str(tmp_path / "missing"),))
    assert paths.find_tesseract_cmd() is None
