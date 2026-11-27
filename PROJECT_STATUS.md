# Engram — Project Status

**Last updated:** 2026-11-27

## Current state
The project has moved to macOS and is following a new phased plan.
Phase 0 (re-orientation and cleanup) is complete: app naming and
identifiers, removal of template code and the popup's CDN import,
a Tauri 2.x update, and the first Architecture Decision Records in
docs/decisions/. Phase 1 (run on macOS) is next.

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
Phase 1 of the new plan: run on macOS (build the sidecar and app
for Apple Silicon and get the full capture pipeline working).

## Known open items
- OCR still picks up UI chrome within a scoped window (documented
  in README Phase 4/7 sections)
- Sidecar model/data paths use dev-relative paths, not yet resolved
  for real installer distribution (flagged since Phase 2/3)
- Connection-surfacing threshold (0.9) may need retuning with more
  real usage data