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
  app starts, waits for and stops cleanly (ADR 0004), Homebrew
  Tesseract lookup (replaced by Apple Vision in Phase 4), native-resolution Retina capture, popup placed
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
- Phase 4 (smarter capture) is complete: window text read through the
  macOS Accessibility API first (web content, URL, editor documents,
  never secure fields), Apple Vision OCR as the fallback replacing
  Tesseract (ADR 0009); change-aware recapture with dwell and interval
  settings applied live, near-duplicates never stored, popups only for
  connections, deterministic clean-up and no LLM rewriting after it was
  measured inventing content (ADR 0010); system dialogs ignored; URL,
  text source and trigger stored; "Capture now" made secondary.
- Phase 5 (recall) is complete: a Recall page as the home screen;
  deterministic local-time parsing; activity questions answered from
  sessions by code, period summaries, and grounded content answers with
  checked citations and abstention, streamed to the UI (ADR 0012);
  Qwen3-4B-Instruct-2507 replaces TinyLlama after a comparison with
  Phi-4-mini (ADR 0011); recall history in the encrypted store; a
  30-question evaluation with 100% answer accuracy on the chosen model.
- Phase 6 (consolidation and forgetting) is complete: finished days are
  grouped into episodes and summarised with cited sources, then
  summarised as a day (ADR 0013), at startup, when idle on power, or on
  demand; Recall uses day summaries and episodes; a morning recap card;
  open loops found by rules and confirmed yes/no by the model;
  forgetting by design with Never as the default, a preview before it
  is turned on, and Keep and recall-refresh protection (ADR 0014); small
  talk and activity window titles handled in Recall.
- Phase 7 (the presence) is complete: menu-bar mode with an optional Dock
  icon and a fuller tray menu; a floating, draggable, non-activating mark
  on all Spaces with idle, capturing, connection, kept and paused looks;
  a Spotlight-style ask panel (Option-Space) that streams Recall answers
  and saves notes with Cmd-Return; Keep (Option-Shift-K) captures and
  pins the front window; configurable shortcuts with conflict checks;
  the corner popup retired in favour of the mark and panel; launch at
  login (off by default); Vision OCR reads multi-column screens column
  by column; IBM Plex bundled instead of loaded from Google Fonts
  (ADR 0015).

Under the original plan, Phases 1-10 were completed (see README.md for full phase-by-phase details).
Working local-first "second brain" app: native Tauri shell, local AI
sidecar (TinyLlama + embeddings + Whisper + OCR), SQLite +
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
Phase 8 of the new plan: proof (measuring that Engram actually helps).

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
- The floating mark and ask panel rely on tauri-nspanel (a community
  crate) and Tauri's macos-private-api; Option-Space can clash with apps
  that use it, and can be changed in Settings
- Connection-surfacing threshold (0.9) checked against a fixture
  set (ADR 0006); revisit with more real usage