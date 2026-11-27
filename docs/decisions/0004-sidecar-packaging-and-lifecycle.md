# 0004: Sidecar packaging and lifecycle

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

The AI engine is a Python program with heavy native dependencies:
llama.cpp, PyTorch, CTranslate2, ONNX Runtime and Chroma. The desktop app
starts it as a Tauri sidecar and talks to it over HTTP on 127.0.0.1:8000.

On Windows this arrangement had three loose ends. The app spawned the engine
and forgot about it, so quitting the app could leave an orphaned engine
holding port 8000, and the next launch would talk to the stale one. The
frontend fired requests as soon as it rendered, while the engine was still
loading its models, so the first screens failed. And there was no way to
work on the engine without rebuilding the sidecar binary every time.

Tauri's `externalBin` bundles exactly one executable per target triple,
named `engram-ai-engine-<triple>`, which constrains how the engine can be
packaged.

## Decision

**Packaging: a PyInstaller onefile binary.** `scripts/build-sidecar.sh`
builds the engine from the committed `ai-engine/engram-ai-engine.spec` and
copies the result to `app/src-tauri/binaries/engram-ai-engine-aarch64-apple-darwin`.
A onedir build would start faster, because it skips unpacking, but it is a
folder of hundreds of files and Tauri's `externalBin` expects a single
executable. Shipping the folder as a resource with a small launcher would
work, but it adds moving parts and code-signing work that we do not need
yet. UPX compression is off because it breaks macOS code signatures. Models
are not bundled into the binary (see ADR 0003), which keeps it to a size
PyInstaller handles comfortably.

**Lifecycle: the shell owns the engine.**

- On startup the shell resolves the data and model directories, spawns the
  sidecar with them in its environment, and keeps the child process handle
  in managed state. The engine's output is forwarded to the app log with an
  `[engine]` prefix.
- A background task polls `/health` every half second. When the engine
  answers, the shell records the state as ready and emits an `engine-status`
  event. If the engine exits early, or does not answer within 120 seconds,
  the state becomes failed with a reason. An `engine_status` command lets
  the frontend read the current state when it mounts, so it cannot miss an
  event that fired first.
- Until the engine is ready the frontend shows a calm "Starting Engram"
  screen instead of pages whose requests would fail, and on failure it says
  what went wrong. The window tracker also waits for the engine before
  logging activity or triggering captures.
- On `RunEvent::Exit` the shell kills the sidecar, so quitting from the tray
  never leaves an engine behind.

**Development: `ENGRAM_DEV_ENGINE=1`.** With this variable set the shell does
not spawn the sidecar. It waits for an engine that the developer is already
running from the virtual environment, so engine changes take effect on a
restart of `python main.py` rather than a full PyInstaller build.

## Consequences

Quitting Engram stops the engine, the interface no longer shows
errors while models load, and engine development is quick. The cost of
onefile is startup time: each launch unpacks the bundle (about 330 MB) to a
temporary folder before Python starts, on top of loading three models. On an
M5 MacBook Air this measured about 30 seconds to ready, and 82 seconds on the
first launch of a freshly built binary while macOS scanned it. The 120-second
readiness timeout leaves room for that and for slower machines.

The frozen engine must call `multiprocessing.freeze_support()` before it
imports anything heavy. Without it, the first helper process a library
starts re-runs the whole engine, which loaded every model twice and crashed
in llama.cpp's Metal teardown when the duplicate could not bind the port.

Stopping uses SIGTERM before SIGKILL, because the onefile binary is a
bootloader with the real engine as its child: SIGTERM is forwarded and the
whole tree exits in under a second, while SIGKILL on the bootloader would
orphan the engine. If the app itself crashes or is killed, the engine notices
within about two seconds through `ENGRAM_PARENT_PID` and shuts itself down
(added in Phase 2, see ADR 0005).

If startup time becomes a problem, the onedir-plus-launcher approach above
is the next step, and this record should be superseded when that happens.
