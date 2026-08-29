from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer
import os

DATA_DIR = Path(
    os.environ.get(
        "ENGRAM_DATA_DIR",
        str(Path(__file__).parent / "data"),
    )
)
DATA_DIR.mkdir(exist_ok=True, parents=True)

_client = chromadb.PersistentClient(path=str(DATA_DIR / "chroma"))
_collection = _client.get_or_create_collection(name="memories")

print("Loading embedding model, this may take a moment...")
_embedder = SentenceTransformer("all-MiniLM-L6-v2")
print("Embedding model loaded successfully.")


def embed_text(text: str) -> list[float]:
    return _embedder.encode(text).tolist()


def add_to_vector_store(memory_id: str, content: str) -> None:
    embedding = embed_text(content)
    _collection.add(
        ids=[memory_id],
        embeddings=[embedding],
        documents=[content],
    )


def query_vector_store(query_text: str, n_results: int = 5, exclude_id: str | None = None) -> list[dict]:
    query_embedding = embed_text(query_text)
    # Fetch a couple extra in case we need to filter out exclude_id
    fetch_count = n_results + 1 if exclude_id else n_results
    results = _collection.query(
        query_embeddings=[query_embedding],
        n_results=fetch_count,
    )
    if not results["ids"] or not results["ids"][0]:
        return []

    matches = []
    for i, mid in enumerate(results["ids"][0]):
        if exclude_id and mid == exclude_id:
            continue
        matches.append({
            "id": mid,
            "distance": results["distances"][0][i],
        })
    return matches[:n_results]