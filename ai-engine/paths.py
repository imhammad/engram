"""Where the engine keeps its data and models, and how it finds Tesseract.

This module only uses the standard library so it can be imported (and tested)
without loading any heavy dependencies. Importing it also switches the Hugging
Face libraries to offline mode, so it must be imported before
sentence-transformers or faster-whisper.
"""

import os
import shutil
from pathlib import Path

# The engine never reaches the network at runtime. Models are provisioned once,
# explicitly, by scripts/fetch_models.py. These must be set before any Hugging
# Face library is imported.
for _var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
    os.environ.setdefault(_var, "1")

ENGINE_DIR = Path(__file__).resolve().parent

LLM_FILENAME = "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
EMBEDDER_DIRNAME = "all-MiniLM-L6-v2"
WHISPER_DIRNAME = "faster-whisper-base.en"

HOMEBREW_TESSERACT_PATHS = (
    "/opt/homebrew/bin/tesseract",  # Apple Silicon
    "/usr/local/bin/tesseract",  # Intel
)


class MissingModelError(RuntimeError):
    """Raised when a model has not been provisioned into the models directory."""


def get_data_dir() -> Path:
    """Directory for engram.db and the Chroma index.

    The desktop app passes ENGRAM_DATA_DIR (under Application Support). When the
    engine is run on its own during development it falls back to ai-engine/data.
    """
    override = os.environ.get("ENGRAM_DATA_DIR")
    path = Path(override).expanduser() if override else ENGINE_DIR / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_model_dir() -> Path:
    """Directory holding the provisioned models (see scripts/fetch_models.py)."""
    override = os.environ.get("ENGRAM_MODEL_DIR")
    return Path(override).expanduser() if override else ENGINE_DIR / "models"


def _require(path: Path, what: str) -> Path:
    if not path.exists():
        raise MissingModelError(
            f"{what} not found at {path}. Run "
            f"'python ai-engine/scripts/fetch_models.py --dest {path.parent}' once to install it."
        )
    return path


def llm_path() -> Path:
    return _require(get_model_dir() / LLM_FILENAME, "Language model")


def embedder_path() -> Path:
    return _require(get_model_dir() / EMBEDDER_DIRNAME, "Embedding model")


def whisper_path() -> Path:
    return _require(get_model_dir() / WHISPER_DIRNAME, "Speech-to-text model")


def find_tesseract_cmd() -> str | None:
    """Locate the tesseract binary.

    Order: the TESSERACT_CMD environment variable, then PATH, then the usual
    Homebrew locations. The Homebrew fallback matters because a bundled macOS
    app is launched with a minimal PATH that does not include /opt/homebrew/bin.
    """
    override = os.environ.get("TESSERACT_CMD")
    if override:
        return override
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    for candidate in HOMEBREW_TESSERACT_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None
