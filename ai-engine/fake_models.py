"""Lightweight stand-ins for the models, for tests and CI.

Set ENGRAM_FAKE_MODELS=1 and the engine uses these instead of llama.cpp,
sentence-transformers, faster-whisper and Apple Vision OCR. Nothing heavy is
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
    """Answers by quoting the first sentence of source [1] and citing it, or
    says it found nothing when there are no sources. Streams like llama.cpp."""

    def __call__(self, prompt: str, **_kwargs) -> dict:
        return {"choices": [{"text": f"(fake model) {prompt[:40]}"}]}

    def create_chat_completion(self, messages, stream=False, **_kwargs):
        system, user = messages[0]["content"], messages[-1]["content"]
        if "yes or no" in system:
            yes = re.search(r"\btodo\b|need to|remind me|don't forget|by (monday|friday)|deadline|action item", user, re.I)
            return {"choices": [{"message": {"content": "yes" if yes else "no"}}]}
        if "TITLE:" in system:
            m = re.search(r"\[1\] \(([^)]*)\)\n(.+)", user)
            where = m.group(1).split("; ")[-1].split(" · ")[-1] if m else "Work"
            first = re.split(r"(?<=[.!?])\s", m.group(2).strip())[0].rstrip(".") if m else "Worked"
            text = f"TITLE: {' '.join(where.split()[:6])}\nSUMMARY: {first} [1]."
            return {"choices": [{"message": {"content": text}}]}
        if "episodes" in system:
            m = re.search(r"\[1\] (.+?) \(", user)
            text = f"Worked on {m.group(1)} [1]." if m else "I couldn't find that in your memories."
            return {"choices": [{"message": {"content": text}}]}
        m = re.search(r"\[1\] \([^)]*\)\n(.+)", user)
        if m:
            first = re.split(r"(?<=[.!?])\s", m.group(1).strip())[0].rstrip(".")
            text = f"{first} [1]."
        else:
            text = "I couldn't find that in your memories."
        if not stream:
            return {"choices": [{"message": {"content": text}}]}
        return iter([{"choices": [{"delta": {"content": w + " "}}]} for w in text.split(" ")])


def ocr_text(_region: dict | None) -> str:
    return os.environ.get(FAKE_OCR_TEXT_ENV, DEFAULT_OCR_TEXT)


def transcribe() -> str:
    return DEFAULT_TRANSCRIPT
