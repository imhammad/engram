# Engram

![CI](https://github.com/imhammad/engram/actions/workflows/ci.yml/badge.svg)

A privacy-first, local-first "second brain" desktop app. Engram runs
entirely on your machine — no cloud AI calls, no data leaving your
laptop — and helps you query your own working memory using local AI.

## Current status

Engram now targets macOS on Apple Silicon. Under the new phased plan,
Phase 0 (re-orientation and cleanup), Phase 1 (run on macOS), Phase 2
(trust baseline) and Phase 3 (memory store) are complete; Phase 4
(smarter capture) is next. See PROJECT_STATUS.md for
details and docs/decisions/ for the architecture decision records.
The phase sections below describe the original build.

## Original Phase 1 - Desktop Foundation

- [x] Tauri v2 + React + Vite scaffold
- [x] Tailwind CSS integration
- [x] Verified frontend ↔ Rust IPC bridge
- [x] Basic app shell (sidebar + main content layout)
- [x] Local AI engine (Phase 2)
- [x] Memory graph / RAG pipeline (Phase 3)
- [x] Manual Capture, screen OCR + audio (Phase 4)

## Phase 2 - Local AI Engine (complete)

The AI engine is a Python/FastAPI service running `llama.cpp` with a
quantized local model (currently TinyLlama, for pipeline validation,
a stronger model will replace it before release). It's bundled as a
standalone executable via PyInstaller and launched automatically as
a Tauri sidecar on app startup, so no separate Python process or
manual server start is required. Frontend communicates with it over
local HTTP (`127.0.0.1:8000`), no data ever leaves the device.

**Resolved in the macOS Phase 1:** the sidecar used to locate its
model files through an absolute path into the source tree. Data and
models now live in the app data directory and are passed to the
engine at startup (see docs/decisions/0003).

## Phase 3 - Memory Graph / RAG Pipeline (complete)

Memories are stored in two complementary local stores: SQLite holds
the canonical record (content, source, timestamp), while ChromaDB
holds a vector embedding of each memory (generated locally via
all-MiniLM-L6-v2) for semantic search. Saving a memory writes to
both; searching queries ChromaDB for the nearest matches and
resolves them back to full records via SQLite. The Memories tab in
the app lets you save notes and search them by meaning rather than
exact keywords, fully local, no cloud calls.

## Phase 4 - Manual Capture: Screen OCR + Audio (complete)

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
- ~~Screen OCR captures the full monitor rather than the active
  window~~ resolved: automatic captures now scope to the active
  window's actual bounds (see Phase 6.x fix). Manual "Capture Screen"
  still intentionally captures the full screen by design.
- OCR still picks up UI chrome *within* the scoped window (browser
  bookmarks bar, tab titles) as noise alongside real content. A
  further refinement would filter Tesseract's output by detected
  text size/region to exclude small peripheral UI text — not
  pursued yet, as it adds real complexity for a secondary quality
  improvement rather than a functional gap.
- Audio transcription accuracy varies; a larger Whisper model would
  improve this at the cost of speed/resource usage.


## Phase 5 - Passive Awareness & Automatic Capture (complete)

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

## Phase 6 - Background Service & Tray UX (complete)

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

## Phase 7 - Proactive Suggestions: Connection Surfacing (complete)

Engram now checks every new memory (typed, screen-captured, or
audio-transcribed) against everything already stored, using vector
distance from ChromaDB. If a genuinely close semantic match exists,
the UI surfaces the connection instead of a generic save
confirmation, a teal banner for manual saves, or the popup content
for automatic captures.

**The similarity threshold (0.9) was calibrated empirically, not
guessed:** related-but-differently-phrased content scored 0.61-0.88
in testing, while genuinely unrelated content scored 1.20+, giving
clear separation to threshold against.

## Phase 8 - Dashboard & Activity Visualization (complete)

Added a Dashboard tab showing memory statistics and recent activity:
total memory count, a breakdown by source (typed/screen/audio) shown
as proportional bars, and a feed of recently tracked window activity.
Backed by two new endpoints (GET /stats, GET /activity) built on the
existing SQLite tables, no new storage or capture logic needed,
just querying data Engram was already collecting. This phase was
inserted ahead of planned Phase 9 (CI/CD) specifically to give the
project a visible payoff after several infrastructure-heavy phases.

## Phase 9 - CI/CD & Testing (complete)

GitHub Actions runs on every pull request and push to main, across
three independent jobs: frontend build (Vite), Rust compile check
(cargo check, with Tauri's Linux system dependencies installed in
the runner), and Python unit tests (pytest).

**Test scope is deliberate, not exhaustive:** unit tests currently
cover `db.py` (the SQLite storage layer) with 9 tests, using a
temp-directory-isolated database per test via the same
`ENGRAM_DATA_DIR` environment variable mechanism used by the real
app. Modules that load heavy local AI models on import (TinyLlama,
the embedder, Whisper) are not unit-tested yet, doing so properly
would require mocking model loading, which is a reasonable future
addition but wasn't the highest-value use of this phase's effort.
CI is intentionally fast (seconds, not minutes) as a result.

## Phase 10 - Privacy Dashboard (complete)

A Settings tab gives users direct control over their own captured
data, consistent with the project's privacy-first premise:

- **Export** - downloads a full JSON export of every memory and
  activity log entry, timestamped.
- **Delete everything** - permanently wipes all memories and
  activity history from both SQLite and ChromaDB, behind a two-step
  confirmation (no accidental single-click data loss).
- **Per-memory delete** - individual memories can be removed
  directly from the Memories list, not just via bulk wipe.

This phase exists because a privacy-first pitch without real user
control over captured data would be a contradiction, collecting
data locally instead of in the cloud isn't privacy-respecting on
its own if the user can't see or remove what's been collected.


**Known limitations (tracked for future refinement):**
- Semantic distance is sensitive to phrasing style, a question
  about a topic scores measurably further from a statement about
  the same topic than two similarly-phrased statements would,
  a known property of sentence embeddings generally, not specific
  to this threshold choice.
- Connection surfacing only compares against the single closest
  match; a memory connected to multiple past entries only surfaces
  the nearest one.

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

## What leaves your Mac

Nothing. The engine listens only on 127.0.0.1, on a random port, and
answers only requests that carry a secret generated fresh at every launch,
so web pages and other programs cannot read your memories through it. It
makes no outbound connections while it runs: model downloads happen once,
when you run `fetch_models.py` yourself, and are checked against pinned
hashes.

You can check this two ways:

- The test suite (`ai-engine/tests/test_api.py`) runs saving, searching,
  capture, export and deletion with every outbound socket and DNS lookup
  made to fail. It runs in CI on every pull request.
- `scripts/verify-network-zero.sh` starts the real engine, with the real
  models, inside a macOS sandbox that denies all outbound network access
  except loopback, then saves a memory and searches for it.

Engram also never captures some windows at all (Terminal, password
managers, System Settings, private browsing windows and anything you add in
Settings), removes emails, phone numbers, card numbers and secrets from
captured text before storing it, and lists every capture attempt on the
Ledger page. See docs/threat-model.md for the full picture, including what
is out of scope.

## Storage

Everything Engram keeps is in one encrypted file,
`~/Library/Application Support/dev.engram.app/data/memory.db`: SQLite with
SQLCipher (AES-256) for encryption, FTS5 for keyword search and sqlite-vec
for vector search (ADR 0007). The key is a random 256-bit value stored in
your macOS Keychain and handed to the engine over stdin (ADR 0008).

Search is hybrid: keyword (BM25) and meaning (cosine similarity) rankings are
merged with reciprocal rank fusion, and can be limited by time and app.
Identical text is stored once. Activity is kept as sessions with durations,
which pause when you are idle for five minutes, lock the screen or the Mac
sleeps; the Dashboard shows today's time per app.

`ai-engine/scripts/benchmark_store.py` on an M5 MacBook Air, 10,000
synthetic memories:

| | p50 | p95 |
|---|---|---|
| hybrid search | 29.7 ms | 36.6 ms |
| keyword only | 8.4 ms | 9.4 ms |
| vector only | 20.1 ms | 25.2 ms |

Inserting takes about 0.3 ms per memory (plus embedding), and 10,000
memories take 25.8 MB.

On the first start after updating from an earlier version, Engram moves the
old plain `engram.db` and `chroma/` into a `backup-before-phase3-...` folder
next to `data/` and imports everything into the encrypted store. Delete that
backup folder once you have checked your memories came across, since it is
not encrypted.

## Tech Stack

- **Frontend:** React, TypeScript, Vite, Tailwind CSS
- **Desktop shell:** Tauri v2 (Rust)
- **AI engine:** Python, FastAPI, llama.cpp (Metal), sentence-transformers, faster-whisper, Tesseract
- **Storage:** one SQLite file: SQLCipher (encryption), FTS5 (keywords), sqlite-vec (vectors)

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
│ SQLite: SQLCipher, FTS5, sqlite-vec │
│ (local storage only) │
└──────────────────────┘

## Development on macOS

### Prerequisites

- Apple Silicon Mac running a recent macOS
- Xcode Command Line Tools: `xcode-select --install`
- Homebrew packages: `brew install python@3.11 node cmake tesseract`
- Rust via rustup (make sure `~/.cargo/bin` is on your PATH)

### Python engine

Create the virtual environment and install the pinned dependencies.
llama-cpp-python is compiled from source, and the `CMAKE_ARGS` setting
builds it with Metal so the language model runs on the GPU:

```bash
cd ai-engine
python3.11 -m venv .venv
CMAKE_ARGS="-DGGML_METAL=on" .venv/bin/pip install -r requirements.txt
```

`requirements.in` lists the top-level dependencies and
`requirements-dev.txt` the development tools (pytest, PyInstaller);
`requirements.txt` is the lock generated from them on macOS.

### Models (one-time, explicit download)

The engine never downloads anything while it runs. Install the three
models once; every file is pinned to a revision and checked against a
SHA-256 hash:

```bash
ai-engine/.venv/bin/python ai-engine/scripts/fetch_models.py
```

They go to `~/Library/Application Support/dev.engram.app/models`. If
`ai-engine/models` already holds the TinyLlama file, it is copied
instead of downloaded. Use `--verify` to check an existing install.

If you have memories from before the macOS move in `ai-engine/data`,
copy them into the app data directory once (this never moves or
overwrites anything):

```bash
ai-engine/.venv/bin/python ai-engine/scripts/migrate_dev_data.py
```

### Build the sidecar and run the app

```bash
scripts/build-sidecar.sh
cd app
npm install
npm run tauri dev
```

`build-sidecar.sh` packages the engine with PyInstaller into
`app/src-tauri/binaries/engram-ai-engine-aarch64-apple-darwin`. The app
starts it, shows "Starting Engram" until it answers, and stops it on
quit.

### Working on the engine without rebuilding the sidecar

Run the engine from the venv, then start the app with
`ENGRAM_DEV_ENGINE=1` so it connects to that engine instead of
spawning the sidecar. The engine requires a token, so pick one and use the
same token and port in both terminals:

The engine also needs the database key on stdin; the app creates it in the
Keychain the first time it runs, and `security` reads it back:

```bash
export ENGRAM_TOKEN="$(openssl rand -hex 32)" ENGRAM_PORT=8765
echo "$ENGRAM_TOKEN"   # copy this into the second terminal
cd ai-engine
security find-generic-password -s dev.engram.app -a database-key -w | \
ENGRAM_DEV_ORIGIN=http://localhost:1420 \
ENGRAM_DATA_DIR="$HOME/Library/Application Support/dev.engram.app/data" \
ENGRAM_MODEL_DIR="$HOME/Library/Application Support/dev.engram.app/models" \
.venv/bin/python main.py
```

```bash
export ENGRAM_TOKEN=<the same token> ENGRAM_PORT=8765
cd app
ENGRAM_DEV_ENGINE=1 npm run tauri dev
```

For API work without the models, `ENGRAM_FAKE_MODELS=1` swaps in
lightweight stand-ins (this is what the tests use).

`ENGRAM_DATA_DIR`, `ENGRAM_MODEL_DIR` and `TESSERACT_CMD` can also be
set for the app itself to override the default locations.

### Permissions

macOS asks for two permissions. Screen Recording is needed to read
window titles and capture on-screen text; grant it in System Settings,
Privacy & Security, Screen Recording (the Settings page in Engram shows
the current status and has a button that opens the pane), then restart
Engram. The microphone is requested the first time you press Record.
During `npm run tauri dev` macOS attributes both permissions to the
terminal app you launched it from.

### Tests

```bash
cd ai-engine && .venv/bin/python -m pytest tests/ -v
cd app && npm run build
cd app/src-tauri && cargo check && cargo test --lib
scripts/verify-network-zero.sh
ai-engine/.venv/bin/python ai-engine/scripts/benchmark_store.py
```

### Existing memories from before Phase 2

Memories saved before the trust baseline were not redacted or checked
for noise. To see what would change, run the dry run; add `--apply` to
make the changes, which backs up the database and index first:

```bash
ai-engine/.venv/bin/python ai-engine/scripts/clean_existing_memories.py
```

## Philosophy

Everything runs locally. No user data — screen content, audio,
notes, ever leaves the device. This is a deliberate constraint,
not a limitation.
