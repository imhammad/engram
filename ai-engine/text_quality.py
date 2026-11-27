"""Deterministic clean-up and quality scoring for captured text.

OCR of a window returns the content a person cares about mixed with menu
bars, tab strips, icons read as punctuation, and stray glyphs. This module
removes lines that are mostly noise and scores what is left, so that
unreadable captures are not saved and noisy memories are not offered as
"connections".

It deliberately does not use the language model: a small local model asked
to "clean up" OCR text tends to invent content (see ADR 0005).
"""

import re

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*[A-Za-z]|[A-Za-z]")
_VOWEL = re.compile(r"[aeiouyAEIOUY]")

# A capture is saved only if, after clean-up, it has at least this many
# real-looking words and they make up at least this share of all tokens.
MIN_WORDS = 8
MIN_WORD_RATIO = 0.5
# Captures where more than this share of visible characters are symbols are
# icon strips and image noise read as punctuation.
MAX_SYMBOL_RATIO = 0.3

# The macOS menu bar as OCR reads it: the frontmost app's menus followed by
# status items. A line with three or more of these menu titles is the menu bar.
_MENU_WORDS = {"file", "edit", "view", "window", "help", "history", "bookmarks",
               "profiles", "tab", "format", "go", "insert", "tools", "shell"}


def _is_wordlike(token: str) -> bool:
    """A token that reads as a word: 3+ letters, has a vowel, sane casing."""
    match = _WORD.fullmatch(token.strip(".,;:!?()[]{}\"'"))
    if not match:
        return False
    word = match.group(0)
    if len(word) < 3 or not _VOWEL.search(word):
        return False
    # Real words are lower, Capitalized or UPPER; "eaiA" or "BoX" are OCR noise.
    return word.islower() or word.isupper() or (word[0].isupper() and word[1:].islower())


def _line_is_content(line: str) -> bool:
    tokens = line.split()
    if not tokens:
        return False
    words = sum(1 for t in tokens if _is_wordlike(t))
    # Keep a line if most of it reads as words. Long lines get a little more
    # leeway, but a browser tab strip or icon row (a few words among many
    # glyphs) is dropped.
    ratio = words / len(tokens)
    return (words >= 1 and ratio >= 0.6) or (words >= 5 and ratio >= 0.45)


def _is_menu_bar(line: str) -> bool:
    words = {w.strip(".,:;").lower() for w in line.split()}
    return len(words & _MENU_WORDS) >= 3


def clean_ocr_text(text: str) -> str:
    """Drop the menu bar and noise lines, keeping the readable content."""
    kept = [
        line.strip()
        for line in text.splitlines()
        if _line_is_content(line) and not _is_menu_bar(line)
    ]
    return "\n".join(kept).strip()


def word_stats(text: str) -> tuple[int, float]:
    """Return (number of real-looking words, their share of all tokens)."""
    tokens = text.split()
    if not tokens:
        return 0, 0.0
    words = sum(1 for t in tokens if _is_wordlike(t))
    return words, words / len(tokens)


def symbol_ratio(text: str) -> float:
    visible = [c for c in text if not c.isspace()]
    if not visible:
        return 1.0
    return sum(1 for c in visible if not c.isalnum()) / len(visible)


def noise_reason(text: str) -> str | None:
    """Why a cleaned capture should be dropped, or None if it is worth keeping."""
    words, ratio = word_stats(text)
    if words < MIN_WORDS:
        return f"too few readable words ({words})"
    if ratio < MIN_WORD_RATIO:
        return f"mostly unreadable ({ratio:.0%} real words)"
    sym = symbol_ratio(text)
    if sym > MAX_SYMBOL_RATIO:
        return f"mostly symbols ({sym:.0%})"
    return None


def is_meaningful(text: str) -> bool:
    return noise_reason(text) is None


def strip_menu_bar(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not _is_menu_bar(line))


def assess_capture(raw_text: str) -> tuple[str, str | None]:
    """Clean an OCR capture and decide whether it is worth keeping.

    The noise decision is made on the whole capture (minus the menu bar),
    not on the cleaned text: cleaning removes noisy lines, so a capture that
    is mostly noise would otherwise look tidy once its few readable lines are
    all that is left. Returns (cleaned text, reason to drop or None).
    """
    return clean_ocr_text(raw_text), noise_reason(strip_menu_bar(raw_text))
