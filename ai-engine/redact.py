"""Remove personal data and secrets from text before Engram stores it.

Applied to screen captures, audio transcripts and window titles. Each match
is replaced with a typed marker such as [email] or [secret], so a memory
still reads naturally and it is clear something was removed.

The patterns favour precision: a missed secret is bad, but so is mangling
ordinary prose or code until memories become useless. Every rule has
false-positive tests in tests/test_redact.py.
"""

import math
import re
from collections import Counter

EMAIL = "[email]"
PHONE = "[phone]"
CARD = "[card]"
SECRET = "[secret]"

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)

# Well-known token formats. Order matters only for readability; each is distinct.
_KNOWN_SECRETS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,255}\b"),  # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,255}\b"),  # GitHub fine-grained
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"),  # Anthropic / OpenAI style
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),  # AWS access key id
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),  # Slack
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),  # Google API key
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),  # JWT
]

# KEY=value or KEY: value where the key name looks secret.
_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(
      [A-Z0-9_.\-]*
      (?:password|passwd|pwd|secret|token|api[_\-]?key|apikey|access[_\-]?key|
         private[_\-]?key|client[_\-]?secret|auth[_\-]?token|credentials?|session[_\-]?id)
    )                            # the key must end with the secret word
    (\s*[:=]\s*)
    (?!\[)                       # already redacted
    ("[^"\n]*"|'[^'\n]*'|[^\s,;'"()]+(?![\w(]))   # not a function call
    """
)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# Card numbers: 13 to 19 digits, optionally grouped by spaces or dashes.
_CARD_CANDIDATE = re.compile(r"(?<![\d.])(?:\d[ \-]?){12,18}\d(?![\d.])")

# Phone numbers: international (+country) or the common (555) 555-5555 shapes.
_PHONE = re.compile(
    r"""(?x)
    (?<![\w+])
    (?:
      \+\d{1,3}[\s.\-]?(?:\(?\d{1,4}\)?[\s.\-]?){2,4}\d{2,4}   # +60 12-345 6789
      |
      \(\d{3}\)\s?\d{3}[\s.\-]\d{4}                              # (555) 555-5555
      |
      \b\d{3}[.\-]\d{3}[.\-]\d{4}\b                              # 555-555-5555
    )
    (?![\w])
    """
)

# Long opaque strings: 32+ characters of mixed letters and digits with high entropy.
_OPAQUE = re.compile(r"(?<![A-Za-z0-9/+_\-])[A-Za-z0-9+/_\-]{32,}={0,2}(?![A-Za-z0-9/+_\-])")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _redact_card(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if 13 <= len(digits) <= 19 and _luhn_ok(digits) and len(set(digits)) > 1:
        return CARD
    return match.group(0)


def _shannon_entropy(s: str) -> float:
    counts = Counter(s)
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _redact_opaque(match: re.Match) -> str:
    s = match.group(0)
    core = s.rstrip("=")
    has_digit = any(c.isdigit() for c in core)
    has_upper = any(c.isupper() for c in core)
    has_lower = any(c.islower() for c in core)
    # Paths, identifiers like some_long_function_name and hex hashes of
    # commits are common in code; require a mix of character classes and
    # high entropy so only random-looking strings are removed.
    if "/" in core and core.count("/") > 2:
        return s
    if has_digit and has_upper and has_lower and _shannon_entropy(core) >= 4.0:
        return SECRET
    return s


def redact(text: str | None) -> str:
    """Return text with emails, phone numbers, cards and secrets replaced."""
    if not text:
        return text or ""
    out = _PRIVATE_KEY.sub(SECRET, text)
    for pattern in _KNOWN_SECRETS:
        out = pattern.sub(SECRET, out)
    out = _SECRET_ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}{SECRET}", out)
    out = _EMAIL.sub(EMAIL, out)
    out = _CARD_CANDIDATE.sub(_redact_card, out)
    out = _PHONE.sub(PHONE, out)
    out = _OPAQUE.sub(_redact_opaque, out)
    return out


def contains_sensitive(text: str | None) -> bool:
    return bool(text) and redact(text) != text
