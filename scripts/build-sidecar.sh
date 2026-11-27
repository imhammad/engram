#!/usr/bin/env bash
# Build the Python AI engine into a single executable and place it where
# Tauri's externalBin expects it: app/src-tauri/binaries/engram-ai-engine-<target-triple>.
#
# Usage: scripts/build-sidecar.sh
# Requires ai-engine/.venv set up as described in the README.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="$ROOT/ai-engine"
PYTHON="$ENGINE/.venv/bin/python"
OUT_DIR="$ROOT/app/src-tauri/binaries"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing $PYTHON. Create the venv first (see README, Development on macOS)." >&2
  exit 1
fi

if command -v rustc >/dev/null 2>&1; then
  TARGET="$(rustc -vV | sed -n 's/^host: //p')"
elif [[ -x "$HOME/.cargo/bin/rustc" ]]; then
  TARGET="$("$HOME/.cargo/bin/rustc" -vV | sed -n 's/^host: //p')"
else
  TARGET="aarch64-apple-darwin"
fi

echo "Building engram-ai-engine for $TARGET"
cd "$ENGINE"
"$PYTHON" -m PyInstaller --noconfirm --clean \
  --distpath "$ENGINE/dist" --workpath "$ENGINE/build" \
  engram-ai-engine.spec

mkdir -p "$OUT_DIR"
cp "$ENGINE/dist/engram-ai-engine" "$OUT_DIR/engram-ai-engine-$TARGET"
chmod +x "$OUT_DIR/engram-ai-engine-$TARGET"
echo "Wrote $OUT_DIR/engram-ai-engine-$TARGET ($(du -h "$OUT_DIR/engram-ai-engine-$TARGET" | cut -f1))"
