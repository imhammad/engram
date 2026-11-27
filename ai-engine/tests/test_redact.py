import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from redact import CARD, EMAIL, PHONE, SECRET, contains_sensitive, redact  # noqa: E402

# Test values are built at runtime so this file never contains a string that
# secret scanners would flag as a real credential.
FAKE_GITHUB = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
FAKE_ANTHROPIC = "sk-ant-" + "api03-" + "Xy7Kq2Lm9Np4Rs6Tu8Vw0Za3Bc5De7Fg"
FAKE_OPENAI = "sk-proj-" + "4fT9qLmZ2xR8vK1nP6sW3yB7cD0eG5hJ"
FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0" + ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
FAKE_OPAQUE = "q8Zr3LmN7xT2vB9kP4sW6yH1cF5gJ0dQeRtYuI"


# --- emails, phones, cards -------------------------------------------------

@pytest.mark.parametrize("text", [
    "Contact me at jane.doe@example.com today",
    "mail: hammad+engram@uni.edu.my",
])
def test_emails_are_redacted(text):
    out = redact(text)
    assert EMAIL in out and "@" not in out


@pytest.mark.parametrize("text", [
    "Call +60 12-345 6789 tomorrow",
    "Office: (555) 123-4567",
    "Phone 555-123-4567",
    "+1 415 555 2671",
])
def test_phone_numbers_are_redacted(text):
    assert PHONE in redact(text)


@pytest.mark.parametrize("number", [
    "4111 1111 1111 1111",
    "5500-0000-0000-0004",
    "378282246310005",
])
def test_luhn_valid_cards_are_redacted(number):
    assert redact(f"card {number} exp 12/29") == f"card {CARD} exp 12/29"


def test_luhn_invalid_digit_runs_are_kept():
    text = "order 1234 5678 9012 3456 shipped"
    assert redact(text) == text


# --- secrets ---------------------------------------------------------------

@pytest.mark.parametrize("secret", [FAKE_GITHUB, FAKE_ANTHROPIC, FAKE_OPENAI, FAKE_AWS, FAKE_JWT])
def test_known_token_formats_are_redacted(secret):
    out = redact(f"token is {secret} ok")
    assert secret not in out and SECRET in out


def test_private_key_block_is_redacted():
    block = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmU\n-----END OPENSSH PRIVATE KEY-----"
    out = redact(f"before\n{block}\nafter")
    assert out == f"before\n{SECRET}\nafter"


@pytest.mark.parametrize("line,key", [
    ("DATABASE_PASSWORD=hunter2", "DATABASE_PASSWORD"),
    ("export GITHUB_TOKEN=abc123", "GITHUB_TOKEN"),
    ('api_key: "my-key-value"', "api_key"),
    ("client_secret = s3cr3t", "client_secret"),
    ("AWS_SECRET_ACCESS_KEY=whatever", "AWS_SECRET_ACCESS_KEY"),
])
def test_secret_looking_assignments_keep_key_and_hide_value(line, key):
    out = redact(line)
    assert f"{key}" in out and out.endswith(SECRET)


def test_high_entropy_strings_are_redacted():
    assert redact(f"value {FAKE_OPAQUE} end") == f"value {SECRET} end"


# --- false positives: normal prose and code must survive ---------------------

PROSE = [
    "The meeting moved to 3 pm on 27 November 2026 in room 204.",
    "Revenue grew 12.5% to 1,234,567 dollars in Q3.",
    "Read chapter 4 of the EEG book; the CHB-MIT dataset has 23 patients.",
    "Version 2.12.7 of tauri fixed the window bug.",
    "Call the function before the token bucket refills.",
    "Our password policy requires twelve characters.",
    "The secret to good soup is patience.",
]

CODE = [
    "def calculate_total_price_with_discount_and_tax(items):",
    "const response = await fetch(`${API_BASE}/memories`);",
    "commit 86e429b9f0c3c1d2a4b5e6f708192a3b4c5d6e7f",
    "path = /usr/local/lib/python3.11/site-packages/torch/__init__.py",
    "uuid 4124c037-7acc-43ce-997c-9ca58fbb9554",
    "token_count = len(tokens)",
    "if password is None:",
    "import { invoke } from '@tauri-apps/api/core';",
]


@pytest.mark.parametrize("text", PROSE + CODE)
def test_ordinary_text_is_unchanged(text):
    assert redact(text) == text
    assert not contains_sensitive(text)


def test_empty_and_none():
    assert redact("") == ""
    assert redact(None) == ""


def test_redaction_is_idempotent():
    text = f"mail a@b.co key={FAKE_OPAQUE} card 4111 1111 1111 1111"
    once = redact(text)
    assert redact(once) == once
