# Engram

A privacy-first, local-first "second brain" desktop app. Engram runs
entirely on your machine — no cloud AI calls, no data leaving your
laptop — and helps you query your own working memory using local AI.

## Status: Phase 1 — Desktop Foundation (in progress)

- [x] Tauri v2 + React + Vite scaffold
- [x] Tailwind CSS integration
- [x] Verified frontend ↔ Rust IPC bridge
- [x] Basic app shell (sidebar + main content layout)
- [x] Local AI engine (Phase 2)
- [x] Memory graph / RAG pipeline (Phase 3)
- [x] Manual Capture — screen OCR + audio (Phase 4)

## Phase 2 — Local AI Engine (complete)

The AI engine is a Python/FastAPI service running `llama.cpp` with a
quantized local model (currently TinyLlama, for pipeline validation,
a stronger model will replace it before release). It's bundled as a
standalone executable via PyInstaller and launched automatically as
a Tauri sidecar on app startup, so no separate Python process or
manual server start is required. Frontend communicates with it over
local HTTP (`127.0.0.1:8000`), no data ever leaves the device.

**Known limitation (tracked for Phase 5/packaging):** the sidecar
currently locates its model files via an absolute path into the
source tree, which works in dev but won't survive a real installer
on another machine. This will be resolved when we build proper
resource bundling for distribution.

## Phase 3 — Memory Graph / RAG Pipeline (complete)

Memories are stored in two complementary local stores: SQLite holds
the canonical record (content, source, timestamp), while ChromaDB
holds a vector embedding of each memory (generated locally via
all-MiniLM-L6-v2) for semantic search. Saving a memory writes to
both; searching queries ChromaDB for the nearest matches and
resolves them back to full records via SQLite. The Memories tab in
the app lets you save notes and search them by meaning rather than
exact keywords, fully local, no cloud calls.

## Phase 4 — Manual Capture: Screen OCR + Audio (complete)

Users can manually trigger two capture modes, both saved through the
same memory pipeline as typed notes:

- **Screen capture**: `mss` grabs the current screen, `pytesseract`
  (Tesseract OCR) extracts visible text.
- **Audio capture**: `sounddevice` records an 8-second clip,
  `faster-whisper` (base.en, int8) transcribes it locally.

Both run entirely on-device — no cloud APIs, no continuous
background monitoring. This is a deliberate scope decision: always-on
passive capture (the original "second brain" vision) introduces
significant OS permission, resource-usage, and privacy-UX complexity
that deserves its own dedicated phase rather than being rushed in
alongside the core capture mechanics.

**Known limitations (tracked for future refinement):**
- Screen OCR captures the full monitor rather than the active window,
  so results include UI chrome as noise.
- Audio transcription accuracy varies; a larger Whisper model would
  improve this at the cost of speed/resource usage.

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
