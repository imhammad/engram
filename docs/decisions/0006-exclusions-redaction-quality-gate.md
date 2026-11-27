# 0006: Capture exclusions, redaction and the quality gate

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Once Screen Recording was granted on macOS, the first real day of use showed
three problems. Window titles and captures recorded things nobody should
keep: a Terminal title with the full command line and environment, a GitHub
page with an email address. The manual Capture Screen button captured Engram
itself, because Engram is the window in front when the button is pressed.
And many captures were mostly OCR noise (icon strips read as punctuation,
bookmark bars, the menu bar), which then matched each other and produced
"connections" that made no sense.

An earlier experiment on the wip/capture-cleanup branch asked the local
language model to clean up OCR text. A 1.1B-parameter model given that job
tends to invent content: one stored memory from that period is a paragraph
praising "this text" that never appeared on screen. Clean-up therefore has to
be deterministic.

## Decision

**Exclusions.** Some windows are never captured and their titles are never
stored. Built in: Engram, Terminal, iTerm2, Warp, 1Password, Bitwarden,
Keychain Access and System Settings (matched on the app name), and private
browsing windows. Detecting private windows on macOS turned out to need two
methods. Firefox puts "Private Browsing" in the title, so title patterns
catch it. Chrome-family browsers put nothing in the title: tested on this
Mac, an incognito window and a normal window showing the same page have
identical window information. For Chrome, Edge, Brave, Chromium and Vivaldi
the shell therefore asks the browser for the front window's mode over
AppleScript, once per window switch and again before a manual capture. That
needs the Automation permission, which macOS asks for once; if it is
declined or unanswered within two seconds, the window is treated as normal,
and the Settings page explains this. Safari exposes neither, so Safari
private windows cannot be detected; the Settings page suggests a rule. Users add their own rules, "app name contains" or "window title
contains", stored in SQLite. The list lives in the engine (`exclusions.py`,
GET /exclusions); the Rust tracker fetches it every 30 seconds, and
immediately when the user edits rules, and applies it before it logs
activity or triggers a capture. For an excluded window the activity log gets
the app name and the marker `[excluded]` instead of the title. The engine
applies the same rules again on /activity and /capture as a second check.

**Manual capture targets the previous window.** The tracker remembers the most
recent window that is neither Engram nor excluded. Capture Screen captures
that window's region, re-checking the rules first, and hides Engram's main
window for a moment so it is not in the shot.

**Redaction before storage.** `redact.py` runs over screen captures, audio
transcripts and window titles before they are written anywhere. It replaces
emails, phone numbers, Luhn-valid card numbers, known token formats (GitHub,
`sk-` style API keys, AWS access keys, Slack, Google API keys, JWTs), private
key blocks, `KEY=value` pairs whose key ends in a secret word (TOKEN, SECRET,
PASSWORD, API_KEY and similar), and long high-entropy strings, with typed
markers such as `[email]` and `[secret]`. The rules favour precision; the test
suite includes ordinary prose, numbers, version strings, UUIDs, commit hashes,
file paths and code that must pass through unchanged. Typed notes are stored
as written, because the user chose to save them.

**Quality gate.** `text_quality.py` decides whether a capture is worth
keeping and tidies what is kept. The decision is made on the whole capture,
minus the menu-bar line: at least 8 real-looking words, at least half of all
tokens real-looking words, and no more than 30 percent of characters
symbols. Judging the cleaned text instead does not work, because cleaning
removes noisy lines and a capture that was mostly noise then looks tidy.
What is stored is the cleaned text: noise lines (tab strips, icon rows,
stray glyphs) and the menu bar are dropped, and the capture region is
clipped below the menu-bar strip. On the 22 screen captures in the database
when this was tuned, genuine content scored 64 to 81 percent real words and
noise 24 to 41 percent, so the 50 percent line has a clear margin on both
sides.

**Connections only between real content.** A memory is offered as a
connection only if both it and the new memory pass the gate (typed notes
always pass). The distance threshold was checked with
`scripts/calibrate_connections.py` on a fixture set: related pairs measured
0.22 to 1.15 (squared L2 between normalised embeddings), unrelated pairs 1.38
and above. The existing 0.9 links five of six related pairs and none of the
unrelated ones, so it stays. The bad connections seen in practice came from
noisy captures matching other noisy captures, which the gate now prevents.

**The Capture Ledger.** Every capture attempt is recorded in a `capture_log`
table with the time, app, redacted title, trigger (manual or automatic),
outcome (saved, dropped as noise, excluded, failed), reason and memory id.
The Ledger page lists it, with delete per entry and clear all, and it is part
of the data export and of "delete everything". While a capture runs, the menu
bar item shows "Capturing".

**Existing data.** `scripts/clean_existing_memories.py` applies the same
redaction and gate to memories saved earlier. It is a dry run by default;
`--apply` backs up the database and index first. Whether to apply it is the
user's decision.

## Consequences

Secrets and private windows stay out of storage by default, the user can see
every capture and its outcome, and connections are less often nonsense. The
costs: some genuine but sparse captures (a short dialog, a code editor with
few words) are dropped as noise, and the ledger records that so it is
visible. Redaction will sometimes miss an unusual secret format and
occasionally mark a harmless random-looking string. The exclusion matcher
exists in Python and Rust, and the two must be kept in step; both have
tests.
