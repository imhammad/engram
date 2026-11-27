# Engram — Project Status

**Last updated:** 2026-11-27

## Current state
The project has moved to macOS (Apple Silicon) and is following a new
phased plan.

- Phase 0 (re-orientation and cleanup) is complete: app naming and
  identifiers, removal of template code and the popup's CDN import,
  a Tauri 2.x update, and the first Architecture Decision Records in
  docs/decisions/.
- Phase 1 (run on macOS) is complete: a Mac Python environment with
  Metal-accelerated llama.cpp, data and models in Application Support
  with explicit, checksummed model provisioning and a network-zero
  runtime (ADR 0003), an Apple Silicon PyInstaller sidecar that the
  app starts, waits for and stops cleanly (ADR 0004), Tesseract
  lookup for Homebrew, native-resolution Retina capture, popup placed
  in the screen work area, a Permissions section for Screen Recording
  and the microphone, and a macOS CI job.
- Phase 2 (trust baseline) is complete: the engine requires a
  per-launch 256-bit token on a random loopback port with strict CORS
  (ADR 0005); built-in and user-defined capture exclusions, redaction
  of personal data and secrets, and an OCR quality gate (ADR 0006);
  manual capture of the previous window instead of Engram itself; a
  Capture Ledger page; network-zero proven by blocked-network API tests
  in CI and a sandboxed run of the real engine; docs/threat-model.md.
- Phase 3 (memory store) is complete: one SQLCipher-encrypted SQLite
  file with FTS5 and sqlite-vec replaces ChromaDB (ADR 0007), with the
  key in the macOS Keychain passed over stdin (ADR 0008); numbered
  migrations; traces, episodes and days tables; hybrid search with
  reciprocal rank fusion and time/app filters; content-hash dedupe;
  activity sessions that end on switch, idle, sleep, lock and quit; a
  Today time-per-app panel; one-time import of the old store.

Under the original plan, Phases 1-10 were completed (see README.md for full phase-by-phase details).
Working local-first "second brain" app: native Tauri shell, local AI
sidecar (TinyLlama + embeddings + Whisper + Tesseract), SQLite +
ChromaDB RAG pipeline, manual + automatic (dwell-triggered) capture,
system tray + popup notifications, semantic connection-surfacing,
and a working Dashboard.

## Tech stack
Tauri v2 (Rust) + React/Vite/Tailwind frontend, Python/FastAPI AI
sidecar bundled via PyInstaller, one SQLCipher-encrypted SQLite file
with FTS5 and sqlite-vec.

## Git workflow
Branch per feature → PR → merge → delete branch → sync local main.
Conventional commit prefixes: feat/fix/chore/docs.

## Next planned phase
Phase 4 of the new plan: smarter capture (change-aware recapture while
staying on one window, capture timing settings, Capture Screen made a
secondary action).

## Known open items
- OCR still picks up UI chrome within a scoped window; the quality
  gate drops the worst of it, but bookmark-bar text made of real words
  still passes
- Memories saved before Phase 2 are not redacted; a dry run of
  scripts/clean_existing_memories.py found 17 of 21 to be noise and
  none to redact, and applying it is the owner's call
- Chrome-family incognito windows are detected only with the
  Automation permission; Safari private windows cannot be detected
- The sidecar takes about 30 seconds to start (onefile unpacking plus
  model loading); see ADR 0004 for the onedir alternative
- Window titles and screen content need Screen Recording permission;
  without it, titles are empty and captures only see the desktop
- Losing the Keychain item makes the database unreadable; a key
  export and recovery path is still needed
- The pre-Phase-3 backup folder in Application Support is plain text
  until the owner deletes it
- Connection-surfacing threshold (0.9) checked against a fixture
  set (ADR 0006); revisit with more real usage