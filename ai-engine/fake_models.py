"""Lightweight stand-ins for the models, for tests and CI.

Set ENGRAM_FAKE_MODELS=1 and the engine uses these instead of llama.cpp,
sentence-transformers, faster-whisper and Tesseract. Nothing heavy is
imported, so the whole HTTP API can be exercised with only FastAPI and
Chroma installed.
"""

import hashlib
import math
import os
import re

EMBEDDING_DIM = 384
FAKE_OCR_TEXT_ENV = "ENGRAM_FAKE_OCR_TEXT"
DEFAULT_OCR_TEXT = (
    "Quarterly planning notes: the team agreed to ship the offline search "
    "feature first, then improve the onboarding flow for new users."
)
DEFAULT_TRANSCRIPT = "Remember to review the onboarding flow before the planning meeting."


def enabled() -> bool:
    return os.environ.get("ENGRAM_FAKE_MODELS") == "1"


def embed(text: str) -> list[float]:
    """Deterministic bag-of-words embedding: shared words give nearby vectors."""
    vec = [0.0] * EMBEDDING_DIM
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        h = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big")
        vec[h % EMBEDDING_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeLlama:
    def __call__(self, prompt: str, **_kwargs) -> dict:
        return {"choices": [{"text": f"(fake model) {prompt[:40]}"}]}


def ocr_text(_region: dict | None) -> str:
    return os.environ.get(FAKE_OCR_TEXT_ENV, DEFAULT_OCR_TEXT)


def transcribe() -> str:
    return DEFAULT_TRANSCRIPT
