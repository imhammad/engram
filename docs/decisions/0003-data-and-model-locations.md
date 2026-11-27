# 0003: Where data and models live, and a network-zero runtime

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Until the macOS move, the engine found its database, vector index and
language model through paths compiled into the Rust binary, pointing back
into the source tree (`ai-engine/data` and `ai-engine/models`). That worked
on the development machine and nowhere else: an installed app has no source
tree, and the paths baked in at build time would point at a folder that does
not exist.

Two of the three models were also not under our control at all. The
embedding model (all-MiniLM-L6-v2) and the speech model (faster-whisper
base.en) were fetched from Hugging Face the first time the engine started,
and the Hugging Face libraries would check back with the network on later
starts too. For an app whose promise is that nothing leaves the device, an
engine that quietly reaches the internet on launch is a real problem, even
if what it sends is only a request for a model file.

## Decision

**Data and models live in the app data directory.** On macOS that is
`~/Library/Application Support/dev.engram.app`, with `data/` (SQLite and
Chroma) and `models/` beneath it. The Rust shell resolves the directory at
runtime, creates both folders, and passes them to the engine as
`ENGRAM_DATA_DIR` and `ENGRAM_MODEL_DIR`. Developers can override either
variable. When the engine runs on its own without them, it falls back to
`ai-engine/data` and `ai-engine/models`, which keeps the old development
workflow working.

**Models are provisioned explicitly, once.** `ai-engine/scripts/fetch_models.py`
is the only code that downloads anything. The user runs it deliberately. It
pins every file to a repository revision and a SHA-256 hash, verifies each
file after download and deletes anything that does not match. It copies an
existing TinyLlama file from `ai-engine/models` instead of downloading it
again. The engine loads every model from a local path inside
`ENGRAM_MODEL_DIR` and, if one is missing, fails with a message that names
the script to run.

**The runtime is network-zero.** The engine sets `HF_HUB_OFFLINE`,
`TRANSFORMERS_OFFLINE` and `HF_HUB_DISABLE_TELEMETRY` before any Hugging Face
library is imported, and it turns off Chroma's anonymous telemetry. The only
network traffic at runtime is the loopback connection between the app and
the engine on 127.0.0.1.

**Existing data is copied, never moved.** `ai-engine/scripts/migrate_dev_data.py`
copies `engram.db` and `chroma/` from `ai-engine/data` into the app data
directory. It refuses to run if the destination already has a database, so
it cannot overwrite newer data. We chose a script over an automatic step at
startup because a packaged app cannot reliably know where a source checkout
is, and a one-time copy is easier to reason about when it is visible.

## Consequences

The app works the same way whether it runs from `tauri dev` or from an
installed bundle, and its data sits where macOS users and backup tools
expect to find it. Privacy claims about the runtime can be checked, because
there is exactly one place that downloads anything and the user starts it.

Setting up a new machine now has an extra step: run `fetch_models.py` before
the first launch. If it is skipped, the app shows that the engine could not
start rather than fetching models behind the user's back. Updating a model
means changing the pinned revision and hashes in the script, which is a
deliberate, reviewable change. A future installer will need to run the same
provisioning step or ship the models alongside the app.
