from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from llama_cpp import Llama
import os
from pydantic import BaseModel
from vector_store import add_to_vector_store, query_vector_store
from ocr_capture import capture_screen_text
from audio_capture import record_and_transcribe
from db import (
    init_db, insert_memory, get_all_memories, get_memories_by_ids,
    log_activity, get_stats, get_recent_activity,
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


@app.get("/activity")
def recent_activity(limit: int = 15):
    return get_recent_activity(limit)


@app.post("/memories")
def create_memory(memory: MemoryCreate):
    saved = insert_memory(memory.content)
    add_to_vector_store(saved["id"], saved["content"])
    related = find_related_memory(saved)
    return {"memory": saved, "related_memory": related}

@app.post("/capture/screen")
def capture_screen(request: ScreenCaptureRequest = ScreenCaptureRequest()):
    region_dict = request.region.dict() if request.region else None
    captured_text = capture_screen_text(region_dict)
    if not captured_text:
        return {"saved": False, "reason": "No readable text found on screen."}
    saved = insert_memory(captured_text, source="screen_ocr")
    add_to_vector_store(saved["id"], saved["content"])
    related = find_related_memory(saved)
    return {"saved": True, "memory": saved, "related_memory": related}


@app.post("/capture/audio")
def capture_audio():
    transcript = record_and_transcribe()
    if not transcript:
        return {"saved": False, "reason": "No speech detected."}
    saved = insert_memory(transcript, source="audio_transcription")
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