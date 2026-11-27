"""Benchmark the memory store: insert and hybrid search on synthetic traces.

    ai-engine/.venv/bin/python ai-engine/scripts/benchmark_store.py [--traces 10000]

Uses a temporary encrypted database and random 384-dimensional vectors, so
it measures the store (SQLCipher, FTS5, sqlite-vec, fusion), not the
embedding model. Embedding a query with all-MiniLM-L6-v2 adds a few
milliseconds on top.
"""

import argparse
import os
import random
import secrets
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WORDS = ("budget meeting research citation seizure dataset alignment sidecar tauri engine memory "
         "capture window privacy keychain sqlite vector search keyword review draft schedule club "
         "interview seminar report figure model training results paper deadline notes plan team "
         "design launch release invoice travel flight hotel lecture exam lab chemistry python rust").split()


def random_text(rng: random.Random) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(20, 80)))


def random_vector(np_rng) -> list[float]:
    v = np_rng.standard_normal(384).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


def pct(values: list[float], p: float) -> float:
    return statistics.quantiles(values, n=100)[int(p) - 1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", type=int, default=10_000)
    parser.add_argument("--queries", type=int, default=200)
    args = parser.parse_args()

    tmp = tempfile.mkdtemp(prefix="engram-bench-")
    os.environ["ENGRAM_DATA_DIR"] = tmp
    os.environ["ENGRAM_FAKE_MODELS"] = "1"
    import db
    import store
    from search import hybrid_search, keyword_ranking, vector_ranking

    store.configure(secrets.token_hex(32))
    rng, np_rng = random.Random(7), np.random.default_rng(7)

    start = time.perf_counter()
    for i in range(args.traces):
        db.insert_trace(f"{i} {random_text(rng)}", random_vector(np_rng), source="screen_ocr",
                        app_name=rng.choice(["Chrome", "Pages", "Xcode", "Mail"]))
    insert_s = time.perf_counter() - start

    timings = {"hybrid": [], "keyword": [], "vector": [], "hybrid+filter": []}
    for _ in range(args.queries):
        query = " ".join(rng.choice(WORDS) for _ in range(3))
        vec = random_vector(np_rng)
        for name, fn in (
            ("keyword", lambda: keyword_ranking(query, 20)),
            ("vector", lambda: vector_ranking(vec, 20)),
            ("hybrid", lambda: hybrid_search(query, vec, limit=5)),
            ("hybrid+filter", lambda: hybrid_search(query, vec, limit=5, app="Pages")),
        ):
            t = time.perf_counter()
            fn()
            timings[name].append((time.perf_counter() - t) * 1000)

    store.connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    size_mb = sum(p.stat().st_size for p in Path(tmp).glob("memory.db*")) / 1e6
    print(f"traces: {args.traces}, queries: {args.queries}")
    print(f"insert: {insert_s:.1f} s total, {insert_s / args.traces * 1000:.2f} ms per trace")
    for name, values in timings.items():
        print(f"{name:>14}: p50 {statistics.median(values):6.1f} ms   p95 {pct(values, 95):6.1f} ms")
    print(f"database size: {size_mb:.1f} MB ({size_mb * 1e6 / args.traces / 1000:.1f} KB per trace)")


if __name__ == "__main__":
    main()
