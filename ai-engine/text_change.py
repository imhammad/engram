"""Has a window's content meaningfully changed since its last capture?

Compares word 3-gram shingles (Jaccard similarity). Scrolling a page to a new
section replaces most shingles; a clock ticking, a badge count or a cursor
moving changes only a few. See ADR 0010.
"""

import re

SHINGLE = 3
# At or above this similarity the content counts as unchanged and is not
# recaptured. Below CHANGED_BELOW it is new enough to store again.
CHANGED_BELOW = 0.7
# Any capture this similar to the last one from the same window is a
# near-duplicate and is never stored, whatever triggered it.
NEAR_DUPLICATE = 0.9


def shingles(text: str, size: int = SHINGLE) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.lower())
    if len(words) < size:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}


def similarity(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def changed(previous: str | None, current: str) -> bool:
    return previous is None or similarity(previous, current) < CHANGED_BELOW


def near_duplicate(previous: str | None, current: str) -> bool:
    return previous is not None and similarity(previous, current) >= NEAR_DUPLICATE
