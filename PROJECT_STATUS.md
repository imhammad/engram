# Engram — Project Status

**Last updated:** [30/08/2026]

## Current state
Phases 1-8 complete (see README.md for full phase-by-phase details).
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
Phase 9, CI/CD & Testing (GitHub Actions + unit tests), OR
[whatever you actually decide before switching chats]

## Known open items
- OCR still picks up UI chrome within a scoped window (documented
  in README Phase 4/7 sections)
- Sidecar model/data paths use dev-relative paths, not yet resolved
  for real installer distribution (flagged since Phase 2/3)
- Connection-surfacing threshold (0.9) may need retuning with more
  real usage data