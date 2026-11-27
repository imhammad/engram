from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from llama_cpp import Llama
import os
from datetime import datetime, timezone
from pydantic import BaseModel
from ocr_capture import capture_screen_text
from audio_capture import record_and_transcribe
from db import (
    init_db, insert_memory, get_all_memories, get_memories_by_ids,
    log_activity, get_stats, get_recent_activity,
    delete_memory, delete_all_memories, delete_all_activity,
)
from vector_store import (
    add_to_vector_store, query_vector_store,
    delete_from_vector_store, delete_all_from_vector_store,
)

app = FastAPI(title="Engram AI Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

MODEL_DIR = os.environ.get(
    "ENGRAM_MODEL_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"),
)
MODEL_PATH = os.path.join(MODEL_DIR, "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf")

print(f"Loading local model from: {MODEL_PATH}")
llm = Llama(model_path=MODEL_PATH, n_ctx=2048, verbose=False)
def clean_captured_text(raw_text: str, source_type: str) -> str:
    if source_type == "screen_ocr":
        instruction = (
            "The following text was extracted from a screenshot using OCR. "
            "It likely contains UI clutter like menu items, browser tabs, "
            "bookmarks, buttons, and timestamps mixed in with the real "
            "content. Extract ONLY the meaningful content a person would "
            "actually want to remember. If there is no meaningful content, "
            "respond with exactly: NOTHING_MEANINGFUL"
        )
    else:  # audio_transcription
        instruction = (
            "The following text is a speech-to-text transcript that may "
            "contain minor transcription errors. Lightly clean it up for "
            "clarity without changing its meaning. If it's just noise or "
            "silence with no real content, respond with exactly: "
            "NOTHING_MEANINGFUL"
        )

    prompt = f"{instruction}\n\nRaw text:\n{raw_text}\n\nCleaned content:"
    output = llm(prompt, max_tokens=200, stop=["</s>"])
    cleaned = output["choices"][0]["text"].strip()

    if "NOTHING_MEANINGFUL" in cleaned:
        return ""
    return cleaned
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

CONNECTION_DISTANCE_THRESHOLD = 0.9  # lower distance = more similar; tune based on testing


def find_related_memory(new_memory: dict) -> dict | None:
    matches = query_vector_store(
        new_memory["content"], n_results=1, exclude_id=new_memory["id"]
    )
    if not matches:
        return None
    top_match = matches[0]
    if top_match["distance"] > CONNECTION_DISTANCE_THRESHOLD:
        return None
    related = get_memories_by_ids([top_match["id"]])
    return related.get(top_match["id"])


@app.post("/activity")
def record_activity(entry: ActivityEntry):
    return log_activity(entry.window_title, entry.app_name)

@app.get("/stats")
def stats():
    return get_stats()

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


@app.get("/export")
def export_all_data():
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "memories": get_all_memories(),
        "activity_log": get_recent_activity(limit=10000),
    }

@app.delete("/activity")
def clear_activity_log():
    count = delete_all_activity()
    return {"deleted_count": count}

@app.get("/activity")
def recent_activity(limit: int = 15):
    return get_recent_activity(limit)


@app.post("/memories")
def create_memory(memory: MemoryCreate):
    saved = insert_memory(memory.content)
    add_to_vector_store(saved["id"], saved["content"])
    related = find_related_memory(saved)
    return {"memory": saved, "related_memory": related}

def clean_captured_text(raw_text: str, source_type: str) -> str:
    if source_type == "screen_ocr":
        instruction = (
            "Below is raw OCR text from a screenshot. It mixes real "
            "content with UI clutter (menus, tabs, bookmarks, buttons, "
            "timestamps). Copy out ONLY the exact real content, word for "
            "word, removing the clutter. Do NOT summarize, describe, "
            "comment on, or add anything not present in the raw text. "
            "If there is no real content, output exactly: NOTHING_MEANINGFUL"
        )
    else:
        instruction = (
            "Below is a speech-to-text transcript with possible minor "
            "errors. Correct obvious transcription errors only. Do NOT "
            "add, remove, or invent any content beyond what is stated. "
            "If it's just noise with no real speech, output exactly: "
            "NOTHING_MEANINGFUL"
        )

    prompt = f"{instruction}\n\nRaw text:\n{raw_text}\n\nExact extracted content (no commentary):"
    output = llm(
        prompt,
        max_tokens=200,
        stop=["</s>", "\n\nRaw text:"],
        temperature=0.1,  # low randomness — we want faithful extraction, not creative writing
    )
    cleaned = output["choices"][0]["text"].strip()

    if "NOTHING_MEANINGFUL" in cleaned:
        return ""
    return cleaned

@app.post("/capture/audio")
def capture_audio():
    raw_transcript = record_and_transcribe()
    if not raw_transcript:
        return {"saved": False, "reason": "No speech detected."}

    cleaned_text = clean_captured_text(raw_transcript, "audio_transcription")
    if not cleaned_text:
        return {"saved": False, "reason": "Nothing meaningful found in recording."}

    saved = insert_memory(cleaned_text, source="audio_transcription")
    add_to_vector_store(saved["id"], saved["content"])
    related = find_related_memory(saved)
    return {"saved": True, "memory": saved, "related_memory": related}


@app.post("/capture/screen")
def capture_screen(request: ScreenCaptureRequest = ScreenCaptureRequest()):
    region_dict = request.region.dict() if request.region else None
    captured_text = capture_screen_text(region_dict)
    if not captured_text:
        return {"saved": False, "reason": "No readable text found on screen."}
    saved = insert_memory(captured_text, source="screen_ocr")
    add_to_vector_store(saved["id"], saved["content"])
    return {"saved": True, "memory": saved}


@app.get("/memories")
def list_memories():
    return get_all_memories()

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "engram-ai-engine"}


@app.get("/generate")
def generate(prompt: str):
    output = llm(
        prompt,
        max_tokens=200,
        stop=["</s>"],
    )
    return {"response": output["choices"][0]["text"].strip()}

@app.get("/search")
def search_memories(q: str, limit: int = 5):
    matches = query_vector_store(q, n_results=limit)
    matching_ids = [m["id"] for m in matches]
    memories_by_id = get_memories_by_ids(matching_ids)
    return [memories_by_id[mid] for mid in matching_ids if mid in memories_by_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)