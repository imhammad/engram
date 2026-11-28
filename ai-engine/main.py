import multiprocessing

if __name__ == "__main__":
    # In the PyInstaller build, libraries that start helper processes re-launch
    # this executable. freeze_support() turns those launches into the helper
    # instead of a second copy of the engine loading every model again.
    multiprocessing.freeze_support()

import paths  # first: puts the Hugging Face libraries in offline mode

import hmac
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import fake_models
from audio_capture import record_and_transcribe
import db
import legacy_import
import recall
import store
from db import (
    add_exclusion_rule, close_open_session, delete_all_activity,
    delete_all_capture_log, delete_all_memories, delete_capture_log_entry,
    delete_exclusion_rule, delete_memory, get_all_memories, get_capture_log,
    get_exclusion_rules, get_memories_by_ids, get_recent_activity, get_stats,
    insert_trace, last_capture_of_window, log_capture, nearest_traces,
    recent_captures_of_other_windows, record_switch, time_per_app,
)
from exclusions import (
    BUILTIN_APPS, EXCLUDED_TITLE_MARKER, PRIVATE_TITLE_PATTERNS, SYSTEM_PROCESSES,
    is_system_process, match_exclusion,
)
from ocr_capture import capture_screen_text
from redact import redact
from search import hybrid_search
import text_change
from cleanup import clean_text
from text_quality import accessibility_noise_reason, assess_capture, is_meaningful, word_stats
from vector_store import embed_text

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

# The database key arrives on stdin (ADR 0008). Read it before loading the
# models so a missing key fails fast.
store.configure(store.read_key_from_stdin())

if fake_models.enabled():
    print("ENGRAM_FAKE_MODELS=1: using stand-in models")
    llm = fake_models.FakeLlama()
else:
    from llama_cpp import Llama

    MODEL_PATH = str(paths.llm_path())
    print(f"Loading local model from: {MODEL_PATH}")
    # n_gpu_layers=-1 offloads every layer to the GPU (Metal on Apple Silicon).
    # 4096 tokens holds the recall prompt (about 6,000 characters of sources)
    # plus the answer (ADR 0012).
    llm = Llama(model_path=MODEL_PATH, n_ctx=4096, n_gpu_layers=-1, verbose=False)
    print("Model loaded successfully.")


# Sessions left open by a crash or forced quit must not run on for hours.
db.close_interrupted_sessions()

# First start on the Phase 3 store: bring over the old plain database.
legacy_import.import_legacy(paths.get_data_dir(), embed_text)


class MemoryCreate(BaseModel):
    content: str

class ActivityEntry(BaseModel):
    window_title: str
    app_name: str
    at: str | None = None


class ActivityStop(BaseModel):
    reason: str  # idle | sleep | lock | pause | quit
    ended_at: str | None = None
    # The shell measures idle time and sleep gaps relative to now, which
    # spares it formatting timestamps.
    ended_seconds_ago: float | None = None

class CaptureRegion(BaseModel):
    x: int
    y: int
    width: int
    height: int


class ScreenCaptureRequest(BaseModel):
    region: CaptureRegion | None = None
    app_name: str = ""
    window_title: str = ""
    url: str = ""
    # Text the shell read through the Accessibility API, if any (ADR 0009).
    text: str | None = None
    # dwell: first capture after the dwell delay; recheck: periodic look at
    # the same window, saved only if the content changed; keep: the Keep
    # shortcut, which also pins the memory so it never fades.
    trigger: str = "manual"
    pin: bool = False


class CaptureSettings(BaseModel):
    dwell_seconds: int
    recapture_minutes: int


class LedgerEntry(BaseModel):
    app_name: str = ""
    trigger: str = "auto"
    outcome: str = "excluded"
    reason: str | None = None


class ExclusionRuleCreate(BaseModel):
    kind: str  # "app" or "title"
    pattern: str


# sqlite-vec reports cosine distance (1 - cosine similarity). The Phase 2
# threshold of 0.9 squared L2 between normalised vectors is the same as
# cosine similarity >= 0.55, which is cosine distance <= 0.45.
# scripts/calibrate_connections.py on the fixture set: related pairs 0.22 to
# 1.15, unrelated pairs 1.38 and up, so 0.9 links 5 of 6 related pairs and no
# unrelated ones. The junk "connections" seen in practice were noisy captures
# matching other noisy captures, which the quality gate now stops (ADR 0006).
CONNECTION_DISTANCE_THRESHOLD = 0.45


def passes_quality_gate(memory: dict) -> bool:
    """Typed notes are deliberate; captured text must read as real content."""
    return memory.get("source") == "manual" or is_meaningful(memory.get("content", ""))


def find_related_memory(new_memory: dict, embedding: list[float]) -> dict | None:
    if not passes_quality_gate(new_memory):
        return None
    matches = nearest_traces(embedding, 5, exclude_id=new_memory["id"])
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
    """A window switch: closes the current session and opens a new one."""
    if is_system_process(entry.app_name):
        return {"ignored": True, "reason": "system dialog"}
    # The shell already skips excluded windows; this is the second check.
    excluded = bool(match_exclusion(entry.app_name, entry.window_title, user_rules()))
    title = EXCLUDED_TITLE_MARKER if excluded else redact(entry.window_title)
    return {**record_switch(entry.app_name, title, entry.at), "excluded": excluded}


@app.post("/activity/stop")
def stop_activity(stop: ActivityStop):
    """Activity paused: idle, sleep, screen lock or quit. Ends the open session."""
    reason = stop.reason if stop.reason in ("idle", "sleep", "lock", "pause", "quit") else "idle"
    ended_at = stop.ended_at
    if ended_at is None and stop.ended_seconds_ago:
        ended_at = (datetime.now(timezone.utc) - timedelta(seconds=stop.ended_seconds_ago)).isoformat()
    return {"closed": close_open_session(reason, ended_at)}


@app.get("/activity")
def recent_activity(limit: int = 15):
    return get_recent_activity(limit)


@app.get("/activity/today")
def activity_today(since: str | None = None, limit: int = 8):
    """Time per app since local midnight (or since a given time)."""
    if since is None:
        local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        since = local_midnight.astimezone(timezone.utc).isoformat()
    return {"since": since, "apps": time_per_app(since, limit=limit)}


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
    embedding = embed_text(memory.content)
    saved, created = insert_trace(memory.content, embedding)
    related = find_related_memory(saved, embedding) if created else None
    return {"memory": saved, "related_memory": related, "duplicate": not created}


@app.get("/memories/{memory_id}")
def get_memory(memory_id: str):
    found = get_memories_by_ids([memory_id]).get(memory_id)
    if not found:
        return JSONResponse({"detail": "not found"}, status_code=404)
    return found


@app.delete("/memories/{memory_id}")
def delete_single_memory(memory_id: str):
    return {"deleted": delete_memory(memory_id)}


@app.delete("/memories")
def delete_all_memories_endpoint():
    return {"deleted_count": delete_all_memories()}


@app.get("/search")
def search_memories(q: str, limit: int = 5, since: str | None = None, until: str | None = None, app: str | None = None):
    """Hybrid keyword and semantic search, optionally limited by time and app."""
    ids = hybrid_search(q, embed_text(q), limit=limit, since=since, until=until, app=app)
    by_id = get_memories_by_ids(ids)
    return [by_id[i] for i in ids if i in by_id]


# --- capture --------------------------------------------------------------

def _save_capture(text: str, source: str, trigger: str, app_name: str, title: str,
                  url: str = "", text_source: str = "") -> dict:
    embedding = embed_text(text)
    _, ratio = word_stats(text)
    saved, created = insert_trace(text, embedding, source=source, app_name=app_name, window_title=title,
                                  url=url, quality=round(ratio, 3), text_source=text_source)
    if not created:
        log_capture(trigger, "duplicate", app_name, title, "same text as an existing memory",
                    memory_id=saved["id"], text_source=text_source, url=url)
        return {"saved": False, "reason": "Already saved: the same text is in an existing memory.", "memory": saved}
    log_capture(trigger, "saved", app_name, title, memory_id=saved["id"], text_source=text_source, url=url)
    return {"saved": True, "memory": saved, "related_memory": find_related_memory(saved, embedding)}


def extract_capture_text(request: ScreenCaptureRequest, other_windows: list[str]) -> tuple[str, str, str | None]:
    """Pick the text for a capture: Accessibility text first, OCR as the fallback.

    Returns (text, text_source, reason_dropped). Accessibility text is used
    when, after clean-up, it passes the lighter gate; otherwise the window is
    read with OCR and held to the strict gate.
    """
    if request.text:
        ax_text = clean_text(request.text, other_windows)
        if accessibility_noise_reason(ax_text) is None:
            return ax_text, "accessibility", None
    region_dict = request.region.model_dump() if request.region else None
    raw = capture_screen_text(region_dict)
    cleaned, noise = assess_capture(raw)
    return clean_text(cleaned, other_windows), "ocr", noise


@app.post("/capture/screen")
def capture_screen(request: ScreenCaptureRequest = ScreenCaptureRequest()):
    app_name = request.app_name
    title = redact(request.window_title)
    url = redact(request.url)
    trigger = {"auto": "dwell"}.get(request.trigger, request.trigger)
    if trigger not in ("manual", "dwell", "recheck", "keep"):
        trigger = "manual"
    pin = request.pin or trigger == "keep"

    if is_system_process(app_name):
        return {"saved": False, "reason": "Not captured: system dialog."}
    reason = match_exclusion(request.app_name, request.window_title, user_rules())
    if reason:
        log_capture(trigger, "excluded", app_name, EXCLUDED_TITLE_MARKER, reason)
        return {"saved": False, "reason": f"Not captured: {reason}."}

    others = recent_captures_of_other_windows(app_name, title, url)
    try:
        cleaned, text_source, noise = extract_capture_text(request, others)
    except Exception as exc:  # OCR or screen grab failure
        log_capture(trigger, "failed", app_name, title, str(exc), url=url)
        return {"saved": False, "reason": str(exc)}

    text = redact(cleaned)
    previous = last_capture_of_window(app_name, title, url)
    previous_text = previous["content"] if previous else None

    if trigger == "recheck":
        # Periodic look at the same window: store only if it changed. Unchanged
        # rechecks are not written to the ledger, or it would fill every few minutes.
        if noise or not text_change.changed(previous_text, text):
            return {"saved": False, "unchanged": True, "reason": "No meaningful change."}
        trigger = "changed"
    if noise:
        log_capture(trigger, "dropped-noise", app_name, title, noise, text_source=text_source, url=url)
        return {"saved": False, "reason": f"Nothing worth saving: {noise}."}
    if text_change.near_duplicate(previous_text, text):
        log_capture(trigger, "duplicate", app_name, title, "almost the same as the last capture of this window",
                    memory_id=previous["id"], text_source=text_source, url=url)
        if pin:  # Keep on something already saved: keep that memory
            db.set_pinned(previous["id"], True)
            return {"saved": False, "kept": True, "reason": "Already saved; now kept.", "memory": previous}
        return {"saved": False, "reason": "Already saved: nearly the same as the last capture.", "memory": previous}
    result = _save_capture(text, "screen_ocr", trigger, app_name, title, url, text_source)
    if pin and result.get("memory"):
        db.set_pinned(result["memory"]["id"], True)
        result["kept"] = True
    return result


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
        "system_processes": SYSTEM_PROCESSES,
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


# --- capture settings -----------------------------------------------------
# Applied live: the shell re-reads them every 30 seconds and right after
# they change in Settings.

DWELL_CHOICES = (15, 30, 60)
RECAPTURE_CHOICES = (0, 1, 2, 5)  # minutes; 0 turns recapture off
DEFAULT_CAPTURE_SETTINGS = {"dwell_seconds": 30, "recapture_minutes": 2}


@app.get("/settings/capture")
def get_capture_settings():
    stored = store.get_setting("capture_settings")
    return {**DEFAULT_CAPTURE_SETTINGS, **(json.loads(stored) if stored else {})}


@app.put("/settings/capture")
def put_capture_settings(settings: CaptureSettings):
    if settings.dwell_seconds not in DWELL_CHOICES or settings.recapture_minutes not in RECAPTURE_CHOICES:
        return JSONResponse(
            {"detail": f"dwell_seconds must be one of {DWELL_CHOICES}, recapture_minutes one of {RECAPTURE_CHOICES}"},
            status_code=422,
        )
    store.set_setting("capture_settings", json.dumps(settings.model_dump()))
    return get_capture_settings()


# --- data export ----------------------------------------------------------

@app.get("/export")
def export_all_data():
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "memories": get_all_memories(),
        "activity_sessions": get_recent_activity(limit=100000),
        "capture_log": get_capture_log(limit=100000),
        "exclusion_rules": user_rules(),
        "recall_history": db.get_recall_history(limit=100000),
        "days": [db.get_day(d) for d in db.consolidated_days()],
        "open_loops": db.get_open_loops("open", 1000) + db.get_open_loops("done", 1000) + db.get_open_loops("dismissed", 1000),
    }


# --- misc -----------------------------------------------------------------

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/storage")
def storage_info():
    """For the Settings page: how the store is protected and what was imported."""
    summary = store.get_setting(legacy_import.SUMMARY_KEY)
    return {
        "encrypted": True,
        "cipher": "SQLCipher (AES-256)",
        "key_location": "macOS Keychain, item dev.engram.app",
        "schema_version": store.schema_version(store.connect()),
        "legacy_import": json.loads(summary) if summary else None,
    }


# --- consolidation, recap, forgetting, open loops (Phase 6) -------------------

import threading as _threading

import consolidation
import forgetting

_consolidation_lock = _threading.Lock()
_consolidation_state = {"running": False}


def _local_tz():
    return datetime.now().astimezone().tzinfo


def run_consolidation(day: str | None = None, force: bool = False) -> dict:
    """Consolidate one day (or every pending past day), then apply forgetting."""
    if not _consolidation_lock.acquire(blocking=False):
        return {"running": True, "consolidated": [], "faded": 0}
    _consolidation_state["running"] = True
    try:
        tz = _local_tz()
        if day:
            result = consolidation.consolidate_day(datetime.fromisoformat(day).date(), llm, embed_text, tz, force=force)
            done = [result["day"]] if result else []
        else:
            done = consolidation.consolidate_pending(llm, embed_text, tz)
        faded = forgetting.run()
        return {"running": False, "consolidated": done, "faded": faded.get("faded", 0)}
    finally:
        _consolidation_state["running"] = False
        _consolidation_lock.release()


class ConsolidateRequest(BaseModel):
    day: str | None = None
    force: bool = False


@app.post("/consolidate")
def consolidate_endpoint(body: ConsolidateRequest = ConsolidateRequest()):
    """On demand from Settings, or from the shell when the Mac is idle and on power."""
    return run_consolidation(body.day, body.force)


@app.get("/consolidation")
def consolidation_status():
    last = store.get_setting("last_consolidation")
    return {"running": _consolidation_state["running"],
            "pending_days": [d.isoformat() for d in consolidation.pending_days(_local_tz())],
            "last": json.loads(last) if last else None}


@app.get("/days/{day}")
def get_day_endpoint(day: str):
    found = db.get_day(day)
    return found or JSONResponse({"detail": "not consolidated"}, status_code=404)


@app.get("/recap")
def recap(day: str | None = None):
    """Yesterday (or a given day) as episodes, focused time, top apps and open loops."""
    from datetime import timedelta as _td
    tz = _local_tz()
    target = day or (datetime.now(tz).date() - _td(days=1)).isoformat()
    found = db.get_day(target)
    return {"day": target, "consolidated": found is not None, **(found or {}),
            "open_loops": db.get_open_loops("open", limit=8)}


class ForgettingSetting(BaseModel):
    days: int
    confirm: bool = False


@app.get("/forgetting")
def forgetting_status():
    days = forgetting.get_days()
    return {"days": days, "label": forgetting.CHOICES.get(days, "Custom"),
            "previews": {str(d): forgetting.preview(d) for d in (30, 14, 7)}}


@app.put("/forgetting")
def set_forgetting(body: ForgettingSetting):
    if body.days not in forgetting.CHOICES:
        return JSONResponse({"detail": f"days must be one of {sorted(forgetting.CHOICES)}"}, status_code=422)
    # Turning forgetting on (or making it stricter) needs the preview to have been seen.
    current = forgetting.get_days()
    stricter = body.days > 0 and (current == 0 or body.days < current)
    if stricter and not body.confirm:
        return JSONResponse({"detail": "confirm the preview first", "preview": forgetting.preview(body.days)}, status_code=409)
    forgetting.set_days(body.days)
    return forgetting_status()


class KeepRequest(BaseModel):
    pinned: bool = True


@app.post("/memories/{memory_id}/keep")
def keep_memory(memory_id: str, body: KeepRequest = KeepRequest()):
    """Keep (pin) a memory so it never fades."""
    return {"pinned": body.pinned, "updated": db.set_pinned(memory_id, body.pinned)}


class LoopStatus(BaseModel):
    status: str


@app.get("/open-loops")
def open_loops_endpoint(status: str = "open"):
    return db.get_open_loops(status)


@app.post("/open-loops/{loop_id}")
def set_loop_status(loop_id: str, body: LoopStatus):
    if body.status not in ("open", "done", "dismissed"):
        return JSONResponse({"detail": "status must be open, done or dismissed"}, status_code=422)
    return {"updated": db.set_open_loop_status(loop_id, body.status)}


class RecallQuestion(BaseModel):
    question: str
    stream: bool = True
    save: bool = True


@app.post("/recall")
def recall_endpoint(body: RecallQuestion):
    """Ask Engram. Streams newline-delimited JSON events (meta, token..., done)
    unless stream is false, in which case only the final event is returned."""
    question = body.question.strip()[:500]
    if not question:
        return JSONResponse({"detail": "question is empty"}, status_code=422)

    def events():
        final = None
        for event in recall.recall(question, llm, embed_text):
            if event["type"] == "done":
                final = event
            yield event
        if final is not None and body.save:
            db.add_recall(question, final["answer"], final["route"], final.get("sources", []))

    if not body.stream:
        last = None
        for event in events():
            last = event
        return last

    return StreamingResponse((json.dumps(e) + "\n" for e in events()), media_type="application/x-ndjson")


@app.get("/recall/history")
def recall_history(limit: int = 30):
    return db.get_recall_history(limit)


@app.delete("/recall/history")
def clear_recall_history():
    return {"deleted_count": db.clear_recall_history()}


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
                # Gone, or the id now belongs to another user's process. End the
                # open activity session now, while the time is still known.
                print(f"Engram app (pid {pid}) is gone, shutting down.")
                try:
                    close_open_session("quit")
                except Exception:
                    pass
                os.kill(os.getpid(), signal.SIGTERM)
                return

    threading.Thread(target=loop, name="parent-watchdog", daemon=True).start()


def consolidate_in_background() -> None:
    """At startup, consolidate any finished days that are still raw."""
    def work():
        try:
            result = run_consolidation()
            if result["consolidated"]:
                print(f"Consolidated {len(result['consolidated'])} day(s): {', '.join(result['consolidated'])}")
        except Exception as exc:  # never take the engine down for this
            print(f"Consolidation failed: {exc}")

    _threading.Thread(target=work, name="consolidation", daemon=True).start()


if __name__ == "__main__":
    import uvicorn

    watch_parent()
    consolidate_in_background()

    port = int(os.environ.get("ENGRAM_PORT", "8000"))
    # Loopback only: the engine is never reachable from the network.
    uvicorn.run(app, host="127.0.0.1", port=port)
