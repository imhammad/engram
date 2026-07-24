# Engram

A privacy-first, local-first "second brain" desktop app. Engram runs
entirely on your machine — no cloud AI calls, no data leaving your
laptop — and helps you query your own working memory using local AI.

## Status: Phase 1 — Desktop Foundation (in progress)

- [x] Tauri v2 + React + Vite scaffold
- [x] Tailwind CSS integration
- [x] Verified frontend ↔ Rust IPC bridge
- [x] Basic app shell (sidebar + main content layout)
- [ ] Local AI engine (Phase 2)
- [ ] Memory graph / RAG pipeline (Phase 3)
- [ ] Passive ingestion — screen OCR + audio (Phase 4)

## Tech Stack

- **Frontend:** React, TypeScript, Vite, Tailwind CSS
- **Desktop shell:** Tauri v2 (Rust)
- **AI engine (upcoming):** Python, FastAPI, llama.cpp
- **Storage (upcoming):** ChromaDB (vector) + SQLite (metadata)

## Architecture (high level)

┌─────────────────────┐ IPC ┌──────────────────────┐
│ React Frontend │ <───────────> │ Tauri / Rust Shell │
│ (Tailwind UI) │ │ (native window, │
└─────────────────────┘ │ OS-level access) │
└──────────┬────────────┘
│ local HTTP
▼
┌──────────────────────┐
│ Python AI Sidecar │
│ (FastAPI + llama.cpp)│
└──────────┬────────────┘
│
▼
┌──────────────────────┐
│ ChromaDB + SQLite │
│ (local storage only) │
└──────────────────────┘

## Development

```bash
cd app
npm install
npm run tauri dev
```

## Philosophy

Everything runs locally. No user data — screen content, audio,
notes — ever leaves the device. This is a deliberate constraint,
not a limitation.
