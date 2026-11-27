# Engram threat model

This document describes what Engram stores, where it lives, who can reach it,
what the macOS permissions it asks for allow, and what it does not try to
defend against. It reflects the state after Phase 2 (trust baseline).

## What Engram stores

Everything is kept under `~/Library/Application Support/dev.engram.app`:

- `data/engram.db` (SQLite):
  - `memories`: typed notes (as written), screen captures and audio
    transcripts (redacted, see below), with source and time.
  - `activity_log`: app switches, with the app name and the redacted window
    title, or `[excluded]` for excluded windows.
  - `capture_log` (the Capture Ledger): each capture attempt with time, app,
    redacted title, trigger, outcome and reason.
  - `exclusion_rules`: the user's own never-capture rules.
- `data/chroma/`: the vector index, holding an embedding and a copy of each
  memory's text.
- `models/`: the three model files, installed once by `fetch_models.py`.

Screenshots and audio recordings are not stored. A screen grab exists only in
memory while it is read by OCR; an audio clip is written to a temporary file
for transcription and deleted immediately afterwards.

The data is not encrypted at rest beyond what FileVault provides for the whole
disk. Encrypting the database is planned for Phase 3.

## What is kept out

- **Excluded windows** are never captured and their titles are never stored:
  Engram itself, Terminal, iTerm2, Warp, 1Password, Bitwarden, Keychain Access,
  System Settings, private browsing windows, and anything matching the
  user's rules. Firefox private windows are recognised by their title;
  Chrome, Edge and Brave incognito windows only if the user allows the
  Automation permission, because those browsers do not mark the window title
  on macOS. Safari private windows cannot be detected.
- **Redaction** removes emails, phone numbers, card numbers, API keys and
  tokens, private keys, secret-looking `KEY=value` pairs and long random
  strings from captures, transcripts and titles before they are stored.
- **Noise** captures that are mostly unreadable are not saved; the Ledger
  records that they were dropped.

These are heuristics. They reduce what is stored; they do not guarantee that
nothing sensitive is ever captured from an ordinary window.

## Who can reach the data

- **The network: no one.** The engine binds 127.0.0.1 only and makes no
  outbound connections at runtime. The Hugging Face libraries run in offline
  mode and Chroma telemetry is off. The only code that downloads anything is
  `fetch_models.py`, which the user runs once. This is checked two ways: the
  test suite runs the whole API with outbound sockets and DNS blocked, and
  `scripts/verify-network-zero.sh` runs the real engine under a macOS sandbox
  that denies all outbound network access except loopback.
- **Web pages in a browser: no.** Requests need a per-launch token in a custom
  header, and CORS only approves the app's own origins, so a page cannot read
  the token or make an authenticated request.
- **Other local programs: only with the token.** The engine listens on a
  random port each launch and rejects requests without the 256-bit token.
- **Anything running as the same macOS user: yes.** Such a program can read
  the database files directly, or read the token from the engine's process
  environment. Engram does not defend against malware already running as the
  user.
- **Other macOS users on the same Mac: no**, by the normal permissions on the
  home folder.

## What each macOS permission allows

- **Screen & System Audio Recording.** Lets Engram read window titles and
  capture the pixels of the screen. Engram uses it to read the title of the
  frontmost window and to capture that window's region after it has been in
  front for 30 seconds, or when the user presses Capture Screen. During
  development the permission belongs to the terminal app that runs
  `npm run tauri dev`, which means anything else run from that terminal has
  it too.
- **Microphone.** Lets Engram record audio. It records only while the user
  presses Record, for 8 seconds, and transcribes on the Mac.
- **Automation (Google Chrome and similar).** Lets Engram send AppleScript
  commands to that browser. Engram only asks for the mode of the front window
  (normal or incognito), so that it can skip incognito windows. It sends no
  other commands.
- Engram does not ask for Accessibility, Input Monitoring, Full Disk Access,
  Contacts, Calendars or Location.

## Out of scope

- Malware or another program running as the same user (see above).
- Someone with physical access to an unlocked Mac.
- Backups: Time Machine and other backup tools copy the data folder like any
  other, under whatever protection the backup itself has.
- Shoulder surfing and screen sharing: Engram's own window shows memories.
- Supply-chain attacks on dependencies and models. Model files are pinned to
  revisions and SHA-256 hashes, which protects against a changed download but
  not against a model that was malicious when it was pinned.
- Crashes: if the app crashes rather than quitting, the engine notices
  within about two seconds (it watches the app's process id) and shuts
  itself down.
