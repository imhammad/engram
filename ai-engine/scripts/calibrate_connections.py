"""Measure embedding distances on a small fixture set to choose the
connection threshold used by find_related_memory() in main.py.

Runs the real all-MiniLM-L6-v2 model from the models directory:

    ai-engine/.venv/bin/python ai-engine/scripts/calibrate_connections.py

Distances are squared L2 between normalised embeddings, the same number
Chroma reports: 0 is identical, 2 is opposite, 2 - 2*cos in general.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault(
    "ENGRAM_MODEL_DIR", str(Path.home() / "Library/Application Support/dev.engram.app/models")
)

import paths  # noqa: E402  (offline mode before the model import)
from sentence_transformers import SentenceTransformer  # noqa: E402

# Pairs a person would want linked.
RELATED = [
    ("Meeting with Dr. Lee moved to Thursday to discuss the EEG seizure results",
     "Prepare EEG seizure detection results for the Thursday meeting with Dr. Lee"),
    ("CORAL domain alignment improved cross-dataset accuracy on Siena",
     "Try Euclidean alignment and CORAL to fix cross-dataset generalisation for EEG"),
    ("Tauri sidecar fails to start because the binary name lacks the target triple",
     "externalBin needs engram-ai-engine-aarch64-apple-darwin naming for the sidecar"),
    ("Book flights to Kuala Lumpur for the December conference",
     "Conference in Kuala Lumpur in December, need to arrange travel"),
    ("Research integrity agent checks citations against CrossRef and Semantic Scholar",
     "Citation checker cross-references papers with CrossRef to catch fabricated references"),
    ("Club meeting agenda: resume reviews and mock interviews next week",
     "Next week the CS club runs mock interviews and reviews resumes"),
]

# Pairs that share a topic word or two but should not be linked.
UNRELATED = [
    ("Meeting with Dr. Lee moved to Thursday to discuss the EEG seizure results",
     "Buy groceries: oat milk, coffee beans and rice"),
    ("Tauri sidecar fails to start because the binary name lacks the target triple",
     "Chemistry lab report on titration due Monday"),
    ("Book flights to Kuala Lumpur for the December conference",
     "Fix the popup text overflow in the Engram window"),
    ("Research integrity agent checks citations against CrossRef and Semantic Scholar",
     "Weather is drizzly in Alor Setar with a high of 32 degrees"),
    ("Club meeting agenda: resume reviews and mock interviews next week",
     "Python virtual environment with llama.cpp built for Metal"),
    ("CORAL domain alignment improved cross-dataset accuracy on Siena",
     "Netflix watch list for the weekend"),
    # Typical OCR clutter versus real notes: shared bookmark-bar words only.
    ("Extra Skills Personal Research Blogs College Book Tamisium Project Aletheia Club",
     "Personal research plan for the EEG project this semester"),
]


def main() -> None:
    model = SentenceTransformer(str(paths.embedder_path()), device="cpu")

    def distance(a: str, b: str) -> float:
        ea, eb = model.encode([a, b], normalize_embeddings=True)
        return float(((ea - eb) ** 2).sum())

    rel = [distance(a, b) for a, b in RELATED]
    unrel = [distance(a, b) for a, b in UNRELATED]
    print("related:  ", " ".join(f"{d:.3f}" for d in sorted(rel)))
    print("unrelated:", " ".join(f"{d:.3f}" for d in sorted(unrel)))
    print(f"max related {max(rel):.3f}, min unrelated {min(unrel):.3f}")
    for threshold in (0.6, 0.7, 0.75, 0.8, 0.9, 1.0):
        hits = sum(d <= threshold for d in rel)
        false = sum(d <= threshold for d in unrel)
        print(f"threshold {threshold:.2f}: {hits}/{len(rel)} related linked, {false}/{len(unrel)} unrelated linked")


if __name__ == "__main__":
    main()
