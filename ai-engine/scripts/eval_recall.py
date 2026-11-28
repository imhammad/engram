"""Evaluate Recall on the synthetic three-day memory (evaluation/recall_fixture.py).

    ai-engine/.venv/bin/python ai-engine/scripts/eval_recall.py --model Qwen3-4B-Instruct-2507-Q4_K_M.gguf
    ai-engine/.venv/bin/python ai-engine/scripts/eval_recall.py --fake      # pipeline only, no models

Builds a temporary encrypted store with the real embedding model, loads the
fixture, asks every question through recall.recall() and reports:

- retrieval recall@5: content questions whose gold memory is among the
  sources found (before citation checking);
- citation correctness: answered content and summary questions whose cited
  sources include a gold memory (citations always point at real sources;
  the pipeline removes any that do not);
- answer accuracy: every keyword group matched in the answer;
- abstention: unanswerable questions declined, and answerable content
  questions wrongly declined;
- latency p50/p95 for time to first token and full answer (model routes),
  generation speed and peak memory.
"""

import argparse
import json
import os
import resource
import secrets
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

APP_SUPPORT = Path.home() / "Library" / "Application Support" / "dev.engram.app"


def pct(values, p):
    if not values:
        return float("nan")
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[p - 1]


def matches(answer: str, groups: list[list[str]]) -> bool:
    a = answer.lower()
    return all(any(k.lower() in a for k in group) for group in groups)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="GGUF file name in the models directory")
    parser.add_argument("--fake", action="store_true", help="stand-in models (pipeline check only)")
    parser.add_argument("--json", help="write per-question results here")
    args = parser.parse_args()

    os.environ["ENGRAM_DATA_DIR"] = tempfile.mkdtemp(prefix="engram-eval-")
    os.environ.setdefault("ENGRAM_MODEL_DIR", str(APP_SUPPORT / "models"))
    if args.fake:
        os.environ["ENGRAM_FAKE_MODELS"] = "1"
    if args.model:
        os.environ["ENGRAM_LLM_FILE"] = args.model

    import paths  # noqa: F401  (offline mode)
    import fake_models
    import recall
    import store
    from evaluation import recall_fixture as fx
    from vector_store import embed_text

    store.configure(secrets.token_hex(32))
    fx.load(embed_text)

    if fake_models.enabled():
        llm, model_name = fake_models.FakeLlama(), "fake"
    else:
        from llama_cpp import Llama
        model_name = paths.LLM_FILENAME
        t = time.perf_counter()
        llm = Llama(model_path=str(paths.llm_path()), n_ctx=4096, n_gpu_layers=-1, verbose=False)
        print(f"loaded {model_name} in {time.perf_counter() - t:.1f}s")

    # Consolidate the finished days first, as Engram would overnight.
    import consolidation
    import db
    t0 = time.perf_counter()
    consolidated = consolidation.consolidate_pending(llm, embed_text, fx.TZ, today=fx.NOW.date())
    consolidation_s = time.perf_counter() - t0
    episodes_built = sum(len(db.get_day(d)["episodes"]) for d in consolidated)
    print(f"consolidated {consolidated} into {episodes_built} episodes in {consolidation_s:.1f}s")
    for d in consolidated:
        day = db.get_day(d)
        print(f"  {d}: {day['summary']}")
        for e in day["episodes"]:
            print(f"    - {e['title']}: {e['summary'][:140]}")

    def expand(ids):
        """Episode ids stand for the traces they were built from."""
        eps = db.get_episodes_by_ids([i for i in ids if i not in trace_ids])
        out = set(i for i in ids if i in trace_ids)
        for e in eps.values():
            out |= {src["trace_id"] for src in e["sources"]}
        return out

    trace_ids = {tid for tid, *_ in fx.TRACES}
    rows = []
    for kind, question, groups, gold in fx.QUESTIONS:
        start = time.perf_counter()
        first_token = None
        tokens = 0
        meta, done = {}, {}
        for event in recall.recall(question, llm, embed_text, tz=fx.TZ, now=fx.NOW):
            if event["type"] == "meta":
                meta = event
            elif event["type"] == "token":
                tokens += 1
                if first_token is None:
                    first_token = time.perf_counter() - start
            elif event["type"] == "done":
                done = event
        total = time.perf_counter() - start
        answer = done.get("answer", "")
        found = list(expand([s["id"] for s in meta.get("sources", [])]))
        cited = list(expand([s["id"] for s in done.get("sources", [])]))
        abstained = answer.strip() == recall.NOT_FOUND
        rows.append({
            "kind": kind, "question": question, "route": done.get("route"), "answer": answer,
            "found": found, "cited": cited, "gold": gold, "abstained": abstained,
            "correct": (abstained if kind == "unanswerable" else (not abstained and matches(answer, groups))),
            "retrieved_gold": bool(set(gold) & set(found)) if gold else None,
            "cited_gold": bool(set(gold) & set(cited)) if gold else None,
            "first_token": first_token, "total": total, "tokens": tokens,
            "dropped": done.get("dropped_sentences", 0),
        })
        mark = "ok " if rows[-1]["correct"] else "MISS"
        print(f"{mark} [{kind:<12}] {question}\n      -> {answer[:220]}")

    by = lambda k: [r for r in rows if r["kind"] == k]  # noqa: E731
    content, summary, activity, unans = by("content"), by("summary"), by("activity"), by("unanswerable")
    consolidated_q = by("day") + by("episode")
    model_rows = [r for r in rows if r["route"] in ("content", "summary") and r["tokens"]]
    for r in consolidated_q:
        r["cited_gold"] = bool(set(r["gold"]) & set(r["cited"])) if r["gold"] else None
    answered = [r for r in content + summary + consolidated_q if not r["abstained"]]
    report = {
        "model": model_name,
        "questions": len(rows),
        "retrieval_recall_at_5": sum(r["retrieved_gold"] for r in content) / len(content),
        "citation_correctness": (sum(r["cited_gold"] for r in answered) / len(answered)) if answered else 0,
        "answer_accuracy": {
            "activity": sum(r["correct"] for r in activity) / len(activity),
            "content": sum(r["correct"] for r in content) / len(content),
            "summary": sum(r["correct"] for r in summary) / len(summary),
            "day_and_episode": sum(r["correct"] for r in consolidated_q) / len(consolidated_q),
            "all_answerable": sum(r["correct"] for r in activity + content + summary + consolidated_q) / len(activity + content + summary + consolidated_q),
        },
        "abstention_on_unanswerable": sum(r["abstained"] for r in unans) / len(unans),
        "false_abstention_on_content": sum(r["abstained"] for r in content) / len(content),
        "uncited_sentences_dropped": sum(r["dropped"] for r in rows),
        "first_token_s": {"p50": pct([r["first_token"] for r in model_rows], 50), "p95": pct([r["first_token"] for r in model_rows], 95)},
        "full_answer_s": {"p50": pct([r["total"] for r in model_rows], 50), "p95": pct([r["total"] for r in model_rows], 95)},
        "activity_answer_s": {"p50": pct([r["total"] for r in activity], 50)},
        "tokens_per_s": (sum(r["tokens"] for r in model_rows) / sum(r["total"] - (r["first_token"] or 0) for r in model_rows)) if model_rows else 0,
        "peak_rss_gb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9,
        "consolidation": {"days": len(consolidated), "episodes": episodes_built, "seconds": round(consolidation_s, 1)},
    }
    print(json.dumps(report, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps({"report": report, "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
