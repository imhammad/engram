#!/usr/bin/env bash
# Prove the real Engram engine works with the network switched off.
#
# Runs ai-engine/main.py (real models, real OCR and embedding code) under
# macOS sandbox-exec with every outbound connection denied except loopback,
# then saves a memory and searches for it over the local API. If any part of
# the engine needed the internet (model downloads, telemetry, update checks),
# it would fail to start or the requests would fail.
#
# Usage: scripts/verify-network-zero.sh
# Uses a temporary data directory; your real memories are not touched.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/ai-engine/.venv/bin/python"
MODELS="${ENGRAM_MODEL_DIR:-$HOME/Library/Application Support/dev.engram.app/models}"
WORK="$(mktemp -d -t engram-netzero)"
LOG="$WORK/engine.log"
PROFILE="$WORK/no-network.sb"
TOKEN="$(openssl rand -hex 32)"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
ENGINE_PID=""

cleanup() {
  [[ -n "$ENGINE_PID" ]] && kill "$ENGINE_PID" 2>/dev/null && wait "$ENGINE_PID" 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT

fail() { echo "FAIL: $*"; echo "--- engine log (last 30 lines) ---"; tail -30 "$LOG" 2>/dev/null; exit 1; }

cat > "$PROFILE" <<'SB'
(version 1)
(allow default)
; No network except loopback.
(deny network-outbound)
(allow network-outbound (remote ip "localhost:*"))
(allow network-outbound (remote unix-socket))
; Not even DNS: block the system resolver socket too.
(deny network-outbound (literal "/private/var/run/mDNSResponder"))
SB

echo "Sandbox: outbound network denied except 127.0.0.1"

# 1. Control check: the sandbox really blocks the internet. Resolve and
# reach a public host outside the sandbox first, so a failure inside it is
# down to the sandbox and not to this Mac being offline.
CONTROL_IP="$("$PY" -c 'import socket; ip=socket.gethostbyname("huggingface.co"); socket.create_connection((ip, 443), timeout=5).close(); print(ip)' 2>/dev/null)"
if [[ -z "$CONTROL_IP" ]]; then
  echo "note control: this Mac has no internet right now, so the control check is skipped"
elif sandbox-exec -f "$PROFILE" "$PY" -c "import socket; socket.create_connection((\"$CONTROL_IP\", 443), timeout=5)" 2>/dev/null; then
  fail "control check: the sandbox did not block an outbound connection to $CONTROL_IP"
fi
if sandbox-exec -f "$PROFILE" "$PY" -c 'import socket; socket.getaddrinfo("huggingface.co", 443)' 2>/dev/null; then
  fail "control check: the sandbox did not block DNS"
fi
[[ -n "$CONTROL_IP" ]] && echo "ok   control: $CONTROL_IP:443 is reachable outside the sandbox and blocked inside it; DNS is blocked too"

# 2. Start the real engine inside the sandbox.
cd "$ROOT/ai-engine"
ENGRAM_TOKEN="$TOKEN" ENGRAM_PORT="$PORT" ENGRAM_DATA_DIR="$WORK/data" ENGRAM_MODEL_DIR="$MODELS" \
  sandbox-exec -f "$PROFILE" "$PY" main.py >"$LOG" 2>&1 &
ENGINE_PID=$!

H=(-s -m 5 -H "X-Engram-Token: $TOKEN")
for _ in $(seq 1 180); do
  curl "${H[@]}" "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  kill -0 "$ENGINE_PID" 2>/dev/null || fail "the engine exited while starting"
  sleep 1
done
curl "${H[@]}" "http://127.0.0.1:$PORT/health" | grep -q '"ok"' || fail "the engine did not become ready"
echo "ok   engine started with real models and no network"

# 3. Unauthenticated requests are refused.
code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/memories")"
[[ "$code" == "401" ]] || fail "request without the token returned $code, expected 401"
echo "ok   request without the token is refused (401)"

# 4. Save and search.
curl "${H[@]}" -X POST "http://127.0.0.1:$PORT/memories" -H 'Content-Type: application/json' \
  -d '{"content":"Network zero check: Engram keeps every memory on this Mac."}' | grep -q '"id"' \
  || fail "saving a memory failed"
echo "ok   saved a memory"
curl "${H[@]}" "http://127.0.0.1:$PORT/search?q=where%20are%20memories%20kept" | grep -q "Network zero check" \
  || fail "semantic search did not find the memory"
echo "ok   semantic search found it"

# 5. Nothing in the log suggests a blocked network attempt broke anything.
if grep -qiE "Traceback|ConnectionError|Max retries|Name or service not known|nodename nor servname" "$LOG"; then
  fail "the engine log shows network errors"
fi
echo "ok   no network errors in the engine log"

echo "PASS: the engine works with outbound network access denied"
