"""Text embeddings. Vectors themselves are stored in the memory store
(sqlite-vec, see store.py and db.py); this module only turns text into them."""

import fake_models
from paths import embedder_path

if not fake_models.enabled():
    from sentence_transformers import SentenceTransformer

    print("Loading embedding model, this may take a moment...")
    _embedder = SentenceTransformer(str(embedder_path()), device="cpu")
    print("Embedding model loaded successfully.")


def embed_text(text: str) -> list[float]:
    if fake_models.enabled():
        return fake_models.embed(text)
    return _embedder.encode(text, normalize_embeddings=True).tolist()
