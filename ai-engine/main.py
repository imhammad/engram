import multiprocessing

if __name__ == "__main__":
    # In the PyInstaller build, libraries that start helper processes re-launch
    # this executable. freeze_support() turns those launches into the helper
    # instead of a second copy of the engine loading every model again.
    multiprocessing.freeze_support()

import paths  # first: puts the Hugging Face libraries in offline mode

import hmac
import os
import sys
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import fake_models
from audio_capture import record_and_transcribe
from db import (
    add_exclusion_rule, delete_all_activity, delete_all_capture_log,
    delete_all_memories, delete_capture_log_entry, delete_exclusion_rule,
    delete_memory, get_all_memories, get_capture_log, get_exclusion_rules,
    get_memories_by_ids, get_recent_activity, get_stats, init_db,
    insert_memory, log_activity, log_capture,
)
from exclusions import (
    BUILTIN_APPS, EXCLUDED_TITLE_MARKER, PRIVATE_TITLE_PATTERNS, match_exclusion,
)
from ocr_capture import capture_screen_text
from redact import redact
from text_quality import assess_capture, is_meaningful
from vector_store import (
    add_to_vector_store, delete_all_from_vector_store,
    delete_from_vector_store, query_vector_store,
)

# --- access control -------------------------------------------------------
# The shell generates a fresh random token and port for every launch and
# passes them in the environment. Every request must carry the token; see
# docs/decisions/0005.

TOKEN_HEADER = "X-Engram-Token"
ENGINE_TOKEN = os.environ.get("ENGRAM_TOKEN", "")
if len(ENGINE_TOKEN) < 32:
    sys.exit("ENGRAM_TOKEN is missing or too short. The Engram app sets it; "
             "for development, see 'Working on the engine' in the README.")

# Only the app's own webview may call the engine from a browser context.
ALLOWED_ORIGINS = ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"]
if os.environ.get("ENGRAM_DEV_ORIGIN"):
    ALLOWED_ORIGINS.append(os.environ["ENGRAM_DEV_ORIGIN"])

app = FastAPI(title="Engram AI Engine", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def require_token(request: Request, call_next):
    supplied = request.headers.get(TOKEN_HEADER, "")
    if not hmac.compare_digest(supplied.encode(), ENGINE_TOKEN.encode()):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


# Added after the token check so it wraps it: CORS preflight requests carry
# no custom headers and are answered here, before the token is required.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=[TOKEN_HEADER, "Content-Type"],
)

init_db()

if fake_models.enabled():
    print("ENGRAM_FAKE_MODELS=1: using stand-in models")
    llm = fake_models.FakeLlama()
else:
    from llama_cpp import Llama

    MODEL_PATH = str(paths.llm_path())
    print(f"Loading local model from: {MODEL_PATH}")
    # n_gpu_layers=-1 offloads every layer to the GPU (Metal on Apple Silicon).
    llm = Llama(model_path=MODEL_PATH, n_ctx=2048, n_gpu_layers=-1, verbose=False)
    print("Model loaded successfully.")


class MemoryCreate(BaseModel):
    content: str

class ActivityEntry(BaseModel):
    window_title: str
    app_name: str

class CaptureRegion(BaseModel):
    x: int
    y: int
    width: int
    height: int


class ScreenCaptureRequest(BaseModel):
    region: CaptureRegion | None = None
    app_name: str = ""
    window_title: str = ""
    trigger: str = "manual"  # "manual" or "auto"


class LedgerEntry(BaseModel):
    app_name: str = ""
    trigger: str = "auto"
    outcome: str = "excluded"
    reason: str | None = None


class ExclusionRuleCreate(BaseModel):
    kind: str  # "app" or "title"
    pattern: str


# all-MiniLM-L6-v2 embeddings are normalised and Chroma reports squared L2
# distance, so distance = 2 - 2 * cosine similarity; 0.9 means cosine >= 0.55.
# scripts/calibrate_connections.py on the fixture set: related pairs 0.22 to
# 1.15, unrelated pairs 1.38 and up, so 0.9 links 5 of 6 related pairs and no
# unrelated ones. The junk "connections" seen in practice were noisy captures
# matching other noisy captures, which the quality gate now stops (ADR 0006).
CONNECTION_DISTANCE_THRESHOLD = 0.9


def passes_quality_gate(memory: dict) -> bool:
    """Typed notes are deliberate; captured text must read as real content."""
    return memory.get("source") == "manual" or is_meaningful(memory.get("content", ""))


def find_related_memory(new_memory: dict) -> dict | None:
    if not passes_quality_gate(new_memory):
        return None
    matches = query_vector_store(new_memory["content"], n_results=5, exclude_id=new_memory["id"])
    close = [m for m in matches if m["distance"] <= CONNECTION_DISTANCE_THRESHOLD]
    if not close:
        return None
    candidates = get_memories_by_ids([m["id"] for m in close])
    for match in close:
        candidate = candidates.get(match["id"])
        if candidate and passes_quality_gate(candidate):
            return candidate
    return None


def user_rules() -> list[dict]:
    return get_exclusion_rules()


# --- activity -------------------------------------------------------------

@app.post("/activity")
def record_activity(entry: ActivityEntry):
    # The shell already skips excluded windows; this is the second check.
    if match_exclusion(entry.app_name, entry.window_title, user_rules()):
        return {**log_activity(EXCLUDED_TITLE_MARKER, entry.app_name), "excluded": True}
    return {**log_activity(redact(entry.window_title), entry.app_name), "excluded": False}


@app.get("/activity")
def recent_activity(limit: int = 15):
    return get_recent_activity(limit)


@app.delete("/activity")
def clear_activity_log():
    count = delete_all_activity()
    return {"deleted_count": count}


@app.get("/stats")
def stats():
    return get_stats()


# --- memories -------------------------------------------------------------

@app.get("/memories")
def list_memories():
    return get_all_memories()


@app.post("/memories")
def create_memory(memory: MemoryCreate):
    # Typed notes are stored as written: the user chose to save them.
    saved = insert_memory(memory.content)
    add_to_vector_store(saved["id"], saved["content"])
    related = find_related_memory(saved)
    return {"memory": saved, "related_memory": related}


@app.delete("/memories/{memory_id}")
def delete_single_memory(memory_id: str):
    deleted = delete_memory(memory_id)
    if deleted:
        delete_from_vector_store(memory_id)
    return {"deleted": deleted}


@app.delete("/memories")
def delete_all_memories_endpoint():
    count = delete_all_memories()
    delete_all_from_vector_store()
    return {"deleted_count": count}


@app.get("/search")
def search_memories(q: str, limit: int = 5):
    matches = query_vector_store(q, n_results=limit)
    matching_ids = [m["id"] for m in matches]
    memories_by_id = get_memories_by_ids(matching_ids)
    return [memories_by_id[mid] for mid in matching_ids if mid in memories_by_id]


# --- capture --------------------------------------------------------------

def _save_capture(text: str, source: str, trigger: str, app_name: str, title: str) -> dict:
    saved = insert_memory(text, source=source)
    add_to_vector_store(saved["id"], saved["content"])
    log_capture(trigger, "saved", app_name, title, memory_id=saved["id"])
    related = find_related_memory(saved)
    return {"saved": True, "memory": saved, "related_memory": related}


@app.post("/capture/screen")
def capture_screen(request: ScreenCaptureRequest = ScreenCaptureRequest()):
    app_name = request.app_name
    title = redact(request.window_title)
    trigger = request.trigger if request.trigger in ("manual", "auto") else "manual"

    reason = match_exclusion(request.app_name, request.window_title, user_rules())
    if reason:
        log_capture(trigger, "excluded", app_name, EXCLUDED_TITLE_MARKER, reason)
        return {"saved": False, "reason": f"Not captured: {reason}."}

    region_dict = request.region.model_dump() if request.region else None
    try:
        raw_text = capture_screen_text(region_dict)
    except Exception as exc:  # OCR or screen grab failure
        log_capture(trigger, "failed", app_name, title, str(exc))
        return {"saved": False, "reason": str(exc)}

    cleaned, noise = assess_capture(raw_text)
    text = redact(cleaned)
    if noise:
        log_capture(trigger, "dropped-noise", app_name, title, noise)
        return {"saved": False, "reason": f"Nothing worth saving: {noise}."}
    return _save_capture(text, "screen_ocr", trigger, app_name, title)


@app.post("/capture/audio")
def capture_audio():
    try:
        transcript = redact(record_and_transcribe())
    except Exception as exc:
        log_capture("manual", "failed", "Microphone", "", str(exc))
        return {"saved": False, "reason": str(exc)}
    if not transcript:
        log_capture("manual", "dropped-noise", "Microphone", "", "no speech detected")
        return {"saved": False, "reason": "No speech detected."}
    return _save_capture(transcript, "audio_transcription", "manual", "Microphone", "")


# --- capture ledger -------------------------------------------------------

@app.get("/ledger")
def ledger(limit: int = 200):
    return get_capture_log(limit)


@app.post("/ledger")
def add_ledger_entry(entry: LedgerEntry):
    """Lets the shell record captures it skipped itself, for example excluded windows."""
    return log_capture(entry.trigger, entry.outcome, entry.app_name, EXCLUDED_TITLE_MARKER, entry.reason)


@app.delete("/ledger/{entry_id}")
def delete_ledger_entry(entry_id: str):
    return {"deleted": delete_capture_log_entry(entry_id)}


@app.delete("/ledger")
def clear_ledger():
    return {"deleted_count": delete_all_capture_log()}


# --- exclusions -----------------------------------------------------------

@app.get("/exclusions")
def exclusions():
    return {
        "builtin_apps": BUILTIN_APPS,
        "private_title_patterns": PRIVATE_TITLE_PATTERNS,
        "rules": user_rules(),
    }


@app.post("/exclusions/rules")
def create_exclusion_rule(rule: ExclusionRuleCreate):
    pattern = rule.pattern.strip()
    if rule.kind not in ("app", "title") or not pattern:
        return JSONResponse({"detail": "kind must be 'app' or 'title' and pattern non-empty"}, status_code=422)
    return add_exclusion_rule(rule.kind, pattern)


@app.delete("/exclusions/rules/{rule_id}")
def remove_exclusion_rule(rule_id: str):
    return {"deleted": delete_exclusion_rule(rule_id)}


# --- data export ----------------------------------------------------------

@app.get("/export")
def export_all_data():
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "memories": get_all_memories(),
        "activity_log": get_recent_activity(limit=10000),
        "capture_log": get_capture_log(limit=100000),
        "exclusion_rules": user_rules(),
    }


# --- misc -----------------------------------------------------------------

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/generate")
def generate(prompt: str):
    output = llm(prompt, max_tokens=200, stop=["</s>"])
    return {"response": output["choices"][0]["text"].strip()}


def watch_parent() -> None:
    """Exit when the Engram app that started us is gone.

    The app stops the engine when it quits normally. If the app crashes or
    is killed instead (as `tauri dev` does on every rebuild), nothing would
    stop the engine, so it watches the app's process id and shuts itself
    down cleanly once that process no longer exists.
    """
    import signal
    import threading
    import time

    parent = os.environ.get("ENGRAM_PARENT_PID")
    if not parent or not parent.isdigit():
        return
    pid = int(parent)

    def loop() -> None:
        while True:
            time.sleep(2)
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                # Gone, or the id now belongs to another user's process.
                print(f"Engram app (pid {pid}) is gone, shutting down.")
                os.kill(os.getpid(), signal.SIGTERM)
                return

    threading.Thread(target=loop, name="parent-watchdog", daemon=True).start()


if __name__ == "__main__":
    import uvicorn

    watch_parent()

    port = int(os.environ.get("ENGRAM_PORT", "8000"))
    # Loopback only: the engine is never reachable from the network.
    uvicorn.run(app, host="127.0.0.1", port=port)
