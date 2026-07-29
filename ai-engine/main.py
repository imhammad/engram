from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from llama_cpp import Llama
import os

app = FastAPI(title="Engram AI Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_DIR = os.environ.get(
    "ENGRAM_MODEL_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"),
)
MODEL_PATH = os.path.join(MODEL_DIR, "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf")

print(f"Loading local model from: {MODEL_PATH}")
llm = Llama(model_path=MODEL_PATH, n_ctx=2048, verbose=False)
print("Model loaded successfully.")


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)