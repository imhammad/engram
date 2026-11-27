"""Deterministic clean-up of captured text. No language model involved.

A small local model asked to "clean up" captured text tends to invent
content (ADR 0010), so captures are tidied with plain rules instead:

- whitespace is normalised and repeated lines are kept once;
- common navigation and cookie-banner lines are dropped;
- lines that keep appearing in this app's other windows (site headers,
  sidebars, tab strips) are treated as UI chrome and dropped.
"""

import re
from collections import Counter

# Exact lines (case-insensitive) that are navigation or boilerplate.
BOILERPLATE = {
    "home", "menu", "search", "sign in", "sign up", "log in", "log out", "sign out", "register",
    "skip to main content", "skip to content", "skip navigation", "main menu", "open menu", "close menu",
    "notifications", "messaging", "my network", "jobs", "for business", "try premium for free", "me",
    "accept", "accept all", "accept all cookies", "reject all", "cookie settings", "cookie preferences",
    "manage cookies", "privacy policy", "terms of service", "terms of use", "cookie policy", "help",
    "back to top", "share", "like", "comment", "repost", "send", "follow", "more", "show more",
    "see more", "load more", "next", "previous", "close", "dismiss", "subscribe", "new tab",
}

# A line seen in at least this many of the app's recent captures of other
# windows is chrome rather than content.
CHROME_MIN_REPEATS = 3


def _norm(line: str) -> str:
    return " ".join(line.split())


def chrome_lines(other_captures: list[str]) -> set[str]:
    """Lines that recur across captures of the same app's other windows."""
    counts: Counter[str] = Counter()
    for text in other_captures:
        counts.update({_norm(l).lower() for l in text.splitlines() if _norm(l)})
    return {line for line, n in counts.items() if n >= CHROME_MIN_REPEATS}


def clean_text(text: str, other_captures: list[str] | None = None) -> str:
    chrome = chrome_lines(other_captures or [])
    kept, seen = [], set()
    for raw in text.splitlines():
        line = _norm(raw)
        key = line.lower()
        if not line or key in seen:
            continue
        seen.add(key)
        if key.strip(" .:|·•-") in BOILERPLATE or key in chrome:
            continue
        # Lone numbers and counters ("3", "12 new") carry nothing on their own.
        if re.fullmatch(r"[\d\s.,:+%·•|-]{1,8}( new)?", key):
            continue
        kept.append(line)
    return "\n".join(kept)
