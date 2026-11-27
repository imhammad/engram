from paths import embedder_path, get_data_dir

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

DATA_DIR = get_data_dir()

# Telemetry off: the engine must make no network calls.
_client = chromadb.PersistentClient(
    path=str(DATA_DIR / "chroma"),
    settings=Settings(anonymized_telemetry=False),
)
_collection = _client.get_or_create_collection(name="memories")

print("Loading embedding model, this may take a moment...")
_embedder = SentenceTransformer(str(embedder_path()), device="cpu")
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

def delete_from_vector_store(memory_id: str) -> None:
    _collection.delete(ids=[memory_id])


def delete_all_from_vector_store() -> None:
    all_ids = _collection.get()["ids"]
    if all_ids:
        _collection.delete(ids=all_ids)