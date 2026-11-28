"""Open loops: things the user said they would do, found in their memories.

Candidates are found with rules ("TODO", "remind me to", "I need to",
"don't forget", deadlines). The local model then only answers yes or no:
is this a task the user still has to do? It never rewrites the text, which
is stored as it appeared (ADR 0013).
"""

import hashlib
import re

import db

# Apps whose text is the user's own (notes, messages, code) rather than
# pages they read; commitments in a web article are the author's, not theirs.
READING_APPS = {"google chrome", "safari", "arc", "firefox", "microsoft edge", "brave browser", "chromium",
                "vivaldi", "preview", "books", "kindle"}

PATTERNS = [
    r"\btodo\b[:\s]", r"\bto-do\b", r"\bremind me to\b", r"\bdon'?t forget to\b", r"\bremember to\b",
    r"\bi (?:need|have|must|should|want) to\b", r"\bi'?ll\b", r"\bi will\b", r"\baction items?\b",
    r"\bplease reply by\b", r"\bdeadline\b", r"\bdue (?:on|by|date)\b", r"\bby (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight)\b",
    r"\bfollow up\b", r"\bnext steps?\b",
]
_PATTERN = re.compile("|".join(PATTERNS), re.I)

CLASSIFY_PROMPT = (
    "You decide whether a sentence from the user's own notes, messages or code is a task or commitment "
    "the user still has to do. Answer with one word: yes or no."
)


def candidates(text: str) -> list[str]:
    out = []
    for raw in re.split(r"(?<=[.!?])\s+|\n", text):
        sentence = " ".join(raw.split()).strip(" -*#/")
        if 15 <= len(sentence) <= 240 and _PATTERN.search(sentence):
            out.append(sentence)
    return out


def classify(sentence: str, llm) -> bool:
    import recall
    with recall._llm_lock:
        out = llm.create_chat_completion(
            messages=[{"role": "system", "content": CLASSIFY_PROMPT}, {"role": "user", "content": sentence}],
            stream=False, temperature=0.0, max_tokens=3)
    return out["choices"][0]["message"]["content"].strip().lower().startswith("yes")


def detect_and_store(traces: list[dict], llm) -> int:
    """Find open loops in these traces and store new ones. Returns how many were added."""
    added = 0
    for t in traces:
        if (t.get("app_name") or "").lower() in READING_APPS and t.get("source") != "manual":
            continue
        for sentence in candidates(t["content"]):
            digest = hashlib.sha256(sentence.lower().encode()).hexdigest()
            if db.open_loop_exists(digest):
                continue
            if classify(sentence, llm):
                db.add_open_loop(t["id"], sentence, digest, t.get("app_name") or "", t["created_at"])
                added += 1
    return added
