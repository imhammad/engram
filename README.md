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

Both run entirely on-device, no cloud APIs, no continuous
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


## Phase 5 — Passive Awareness & Automatic Capture (complete)

Engram tracks the active window/application in the background via a
5-second poll, but only *acts* on sustained attention: automatic
screen capture fires once per dwell session, after 30+ seconds on
the same window, not on every poll. Rapid window-switching produces
zero captures, this prevents both CPU waste and a memories table
flooded with near-duplicate noise.

**Automatic capture is screen-only, and audio remains manual-only
by deliberate design, not an oversight.** Screen content is always
the user's own data. Passive audio capture would risk silently
recording other people's voices during calls or in shared spaces,
a real problem both ethically and legally (many jurisdictions
require two-party consent to record conversations). For a
privacy-first app, that tradeoff isn't worth automating; the user
explicitly choosing to hit "record" *is* the consent.

Users can fully pause and resume automatic capture at any time via
a toggle in the Memories tab, since even screen capture should
never feel like silent surveillance the user can't see or control.

**Known limitations (tracked for future refinement):**
- Dwell threshold (30s) and poll interval (5s) are currently fixed
  constants; making these user-configurable is a reasonable future
  addition.
- No visual indicator currently shows *when* an automatic capture
  is actively happening (only that the feature is enabled/paused),
  a brief on-screen notification would improve transparency further.

## Phase 6 — Background Service & Tray UX (complete)

Engram now runs as a true background application rather than
requiring a visible window at all times:

- **System tray icon** with Show/Quit menu, closing the main window
  hides it instead of terminating the app; window tracking and
  automatic capture keep running.
- **Standalone popup window** borderless, always-on-top, anchored
  to the screen corner, dynamically positioned to account for
  display scaling. Appears automatically when a dwell-triggered
  capture succeeds, showing which window was captured, dismissible
  via a close button. Does not steal keyboard focus, so it never
  interrupts the user's current task.

This is the first phase where Engram behaves like the intended
product vision, a quiet, always-available assistant, rather than
an app the user has to actively operate.

**Engineering note:** Tauri v2 requires every window to be
explicitly granted permission in a capabilities file before it can
invoke backend commands, a deliberate security boundary that fails
silently rather than erroring, which cost some debugging time here
and is worth remembering for any future additional windows.

**Known limitations (tracked for future refinement):**
- Popup only triggers on screen-capture events; audio capture
  (manual-only, per Phase 5's privacy reasoning) does not yet
  surface a popup notification.
- No sound/animation on popup appearance, currently silent, which
  may be too subtle for some users to notice.

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
