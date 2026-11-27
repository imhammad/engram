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

Under the original plan, Phases 1-10 were completed (see README.md for full phase-by-phase details).
Working local-first "second brain" app: native Tauri shell, local AI
sidecar (TinyLlama + embeddings + Whisper + Tesseract), SQLite +
ChromaDB RAG pipeline, manual + automatic (dwell-triggered) capture,
system tray + popup notifications, semantic connection-surfacing,
and a working Dashboard.

## Tech stack
Tauri v2 (Rust) + React/Vite/Tailwind frontend, Python/FastAPI AI
sidecar bundled via PyInstaller, SQLite + ChromaDB storage.

## Git workflow
Branch per feature → PR → merge → delete branch → sync local main.
Conventional commit prefixes: feat/fix/chore/docs.

## Next planned phase
Phase 2 of the new plan: trust baseline.

## Known open items
- OCR still picks up UI chrome within a scoped window (documented
  in README Phase 4/7 sections)
- The sidecar takes about 30 seconds to start (onefile unpacking plus
  model loading); see ADR 0004 for the onedir alternative
- If the app crashes rather than quitting, the engine can be left
  running on port 8000
- Window titles and screen content need Screen Recording permission;
  without it, titles are empty and captures only see the desktop
- Connection-surfacing threshold (0.9) may need retuning with more
  real usage data