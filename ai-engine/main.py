from fastapi import FastAPI

app = FastAPI(title="Engram AI Engine")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "engram-ai-engine"}