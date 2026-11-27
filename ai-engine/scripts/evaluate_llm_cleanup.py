"""Does the local LLM clean up captures faithfully? (Evidence for ADR 0010.)

    ai-engine/.venv/bin/python ai-engine/scripts/evaluate_llm_cleanup.py

Runs the clean-up prompt from the wip/capture-cleanup branch through the
bundled TinyLlama on sample captures and measures how much of the output is
not in the input: the share of output words (3+ letters) that never appear in
the source text. A faithful clean-up should score near 0%.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ENGRAM_MODEL_DIR", str(Path.home() / "Library/Application Support/dev.engram.app/models"))

import paths  # noqa: E402
from llama_cpp import Llama  # noqa: E402

# The second, stricter prompt from wip/capture-cleanup.
INSTRUCTION = (
    "Below is raw OCR text from a screenshot. It mixes real content with UI clutter (menus, tabs, "
    "bookmarks, buttons, timestamps). Copy out ONLY the exact real content, word for word, removing "
    "the clutter. Do NOT summarize, describe, comment on, or add anything not present in the raw text. "
    "If there is no real content, output exactly: NOTHING_MEANINGFUL"
)

SAMPLES = {
    "article": "Home  My Network  Jobs  Messaging\nCross-dataset seizure detection notes\n"
               "Most seizure detection models fall apart when they are tested on a hospital's data they "
               "were not trained on. Domain alignment methods such as Euclidean alignment and CORAL reduce "
               "the gap between recordings.\nLike  Comment  Repost  Send",
    "profile": "Paolo Mignone\nSenior ML Engineer · Toronto, ON\n500+ connections\nAbout\n"
               "Building privacy preserving models for clinical signal processing.\nMessage  More",
    "code": "File Edit Selection View Go Run\nmain.py\ndef hybrid_search(query, embedding, limit=5):\n"
            "    depth = max(limit * 4, 20)\n    return reciprocal_rank_fusion(keyword, vector)[:limit]\nLn 12, Col 4",
    "noise": "@ © ® 8 Bie O's AIM & x + +> eaiA 2? BO\nExtra_Skills Personal Research Blogs College Book",
}


def invented_share(source: str, output: str) -> float:
    src = set(re.findall(r"[a-z]{3,}", source.lower()))
    out = re.findall(r"[a-z]{3,}", output.lower())
    return sum(w not in src for w in out) / len(out) if out else 0.0


def main() -> None:
    llm = Llama(model_path=str(paths.llm_path()), n_ctx=2048, n_gpu_layers=-1, verbose=False)
    for name, text in SAMPLES.items():
        prompt = f"{INSTRUCTION}\n\nRaw text:\n{text}\n\nExact extracted content (no commentary):"
        out = llm(prompt, max_tokens=200, stop=["</s>", "\n\nRaw text:"], temperature=0.1)["choices"][0]["text"].strip()
        flat = " ".join(out.split())
        print(f"{name:<8} invented {invented_share(text, out):5.0%}  output: {flat[:150]!r}")


if __name__ == "__main__":
    main()
