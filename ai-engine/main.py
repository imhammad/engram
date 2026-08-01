from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from llama_cpp import Llama
import os
from pydantic import BaseModel
from vector_store import add_to_vector_store, query_vector_store
from ocr_capture import capture_screen_text
from audio_capture import record_and_transcribe
from db import init_db, insert_memory, get_all_memories, get_memories_by_ids, log_activity

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


@app.post("/activity")
def record_activity(entry: ActivityEntry):
    return log_activity(entry.window_title, entry.app_name)


@app.post("/memories")
def create_memory(memory: MemoryCreate):
    saved = insert_memory(memory.content)
    add_to_vector_store(saved["id"], saved["content"])
    return saved

@app.post("/capture/screen")
def capture_screen():
    captured_text = capture_screen_text()
    if not captured_text:
        return {"saved": False, "reason": "No readable text found on screen."}
    saved = insert_memory(captured_text, source="screen_ocr")
    add_to_vector_store(saved["id"], saved["content"])
    return {"saved": True, "memory": saved}

@app.post("/capture/audio")
def capture_audio():
    transcript = record_and_transcribe()
    if not transcript:
        return {"saved": False, "reason": "No speech detected."}
    saved = insert_memory(transcript, source="audio_transcription")
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
    matching_ids = query_vector_store(q, n_results=limit)
    memories_by_id = get_memories_by_ids(matching_ids)
    # preserve the relevance order returned by the vector search
    return [memories_by_id[mid] for mid in matching_ids if mid in memories_by_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)