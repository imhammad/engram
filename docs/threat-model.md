# Engram threat model

This document describes what Engram stores, where it lives, who can reach it,
what the macOS permissions it asks for allow, and what it does not try to
defend against. It reflects the state after Phase 4 (smarter capture).

## What Engram stores

Everything is kept under `~/Library/Application Support/dev.engram.app`:

- `data/memory.db`, one SQLCipher-encrypted SQLite database (ADR 0007, 0008):
  - `traces`: typed notes (as written), screen captures and audio transcripts
    (redacted, see below), with source, app, redacted window title, page URL, where the text came from (app or screen) and time,
    plus their keyword index and vectors.
  - `activity_sessions`: time spent per window, with the app name and the
    redacted window title, or `[excluded]` for excluded windows.
  - `capture_log` (the Capture Ledger): each capture attempt with time, app,
    redacted title, trigger, outcome and reason.
  - `exclusion_rules`, `settings`, and the empty `episodes` and `days`
    tables for later phases.
- `models/`: the three model files, installed once by `fetch_models.py`.
- `backup-before-phase3-*/`: the pre-Phase-3 plain database and Chroma
  folder, moved there during the one-time import. **These are not
  encrypted** and should be deleted once the import has been checked.

Screenshots and audio recordings are not stored. A screen grab exists only in
memory while it is read by OCR; an audio clip is written to a temporary file
for transcription and deleted immediately afterwards.

The database key is a random 256-bit value in the login Keychain (item
`dev.engram.app`, account `database-key`). The app passes it to the engine
over stdin; it is never in argv, the environment or a log.

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
  mode, and the store is SQLite, which has no telemetry. The only code that
  downloads anything is
  `fetch_models.py`, which the user runs once. This is checked two ways: the
  test suite runs the whole API with outbound sockets and DNS blocked, and
  `scripts/verify-network-zero.sh` runs the real engine under a macOS sandbox
  that denies all outbound network access except loopback.
- **Web pages in a browser: no.** Requests need a per-launch token in a custom
  header, and CORS only approves the app's own origins, so a page cannot read
  the token or make an authenticated request.
- **Other local programs: only with the token.** The engine listens on a
  random port each launch and rejects requests without the 256-bit token.
- **Anything running as the same macOS user: partly.** Such a program can
  copy `memory.db` but not read it without the key. It could ask the
  Keychain for the key (macOS may prompt), read the engine's token from its
  environment, or read the engine's memory. Engram does not defend against
  malware already running as the user.
- **Someone with a copy of the file** (a backup drive, a synced folder, a
  disk image): they get ciphertext only, unless they also have the Keychain.
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
- **Accessibility.** Lets Engram read the user interface of other apps:
  text, buttons, fields and window structure, and, in principle, act on
  them. Engram only reads, and only the focused window of the frontmost app
  at capture time: a web page's text and URL, an editor's document, or the
  window's visible text. It never reads secure (password) fields, never
  presses buttons or types, and stops after 6,000 elements, 20,000
  characters or 600 ms. The text goes through the same exclusions, redaction
  and clean-up as any capture. Without the permission Engram reads the
  screen with OCR instead. During development the permission belongs to the
  terminal app running `npm run tauri dev`, so anything run from that
  terminal has it too.
- **Microphone.** Lets Engram record audio. It records only while the user
  presses Record, for 8 seconds, and transcribes on the Mac.
- **Automation (Google Chrome and similar).** Lets Engram send AppleScript
  commands to that browser. Engram only asks for the mode of the front window
  (normal or incognito), so that it can skip incognito windows. It sends no
  other commands.
- Engram does not ask for Input Monitoring, Full Disk Access, Contacts,
  Calendars or Location.

## Out of scope

- Malware or another program running as the same user (see above).
- Someone with physical access to an unlocked Mac.
- Backups: Time Machine and other tools copy `memory.db` like any other file;
  the copy stays encrypted, but restoring it on another Mac needs the
  Keychain item too.
- Losing the Keychain item: the database cannot be recovered without it.
- Shoulder surfing and screen sharing: Engram's own window shows memories.
- Supply-chain attacks on dependencies and models. Model files are pinned to
  revisions and SHA-256 hashes, which protects against a changed download but
  not against a model that was malicious when it was pinned.
- Crashes: if the app crashes rather than quitting, the engine notices
  within about two seconds (it watches the app's process id) and shuts
  itself down.
