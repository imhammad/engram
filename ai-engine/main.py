from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from llama_cpp import Llama

app = FastAPI(title="Engram AI Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # fine for local-only dev; we'll tighten this later
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_PATH = "models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"

print("Loading local model, this may take a moment...")
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