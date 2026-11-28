"""Install the models the Engram engine needs, once, with checksum verification.

The engine itself never downloads anything at runtime (see ADR 0003). This
script is the one explicit step that does, and it is run by the user:

    ai-engine/.venv/bin/python ai-engine/scripts/fetch_models.py

By default models go to ~/Library/Application Support/dev.engram.app/models,
which is where the desktop app looks. Pass --dest to install elsewhere, or
--verify to check an existing install without downloading.

Every file is pinned to a specific repository revision and SHA-256 hash. If a
model file already exists in ai-engine/models (from earlier development), it
is copied instead of downloaded again. The earlier TinyLlama model is no
longer used and is not installed.
"""

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DEST = Path.home() / "Library" / "Application Support" / "dev.engram.app" / "models"
LEGACY_MODEL_DIR = ENGINE_DIR / "models"

# Each entry: target directory inside the models dir ("" for the top level),
# Hugging Face repository, pinned revision, and {file: sha256}.
MODELS = [
    {
        # The answer model for Recall (ADR 0011). Apache-2.0.
        "name": "Qwen3-4B-Instruct-2507 (Q4_K_M)",
        "subdir": "",
        "repo": "unsloth/Qwen3-4B-Instruct-2507-GGUF",
        "revision": "a06e946bb6b655725eafa393f4a9745d460374c9",
        "files": {
            "Qwen3-4B-Instruct-2507-Q4_K_M.gguf": "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597",
        },
    },
    {
        "name": "all-MiniLM-L6-v2 (embeddings)",
        "subdir": "all-MiniLM-L6-v2",
        "repo": "sentence-transformers/all-MiniLM-L6-v2",
        "revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        "files": {
            "1_Pooling/config.json": "4be450dde3b0273bb9787637cfbd28fe04a7ba6ab9d36ac48e92b11e350ffc23",
            "config.json": "953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41",
            "config_sentence_transformers.json": "061ca9d39661d6c6d6de5ba27f79a1cd5770ea247f8d46412a68a498dc5ac9f3",
            "model.safetensors": "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db",
            "modules.json": "84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf",
            "sentence_bert_config.json": "fc1993fde0a95c24ec6c022539d41cf6e2f7c9721e5415d6fb6897472a9cd4b7",
            "special_tokens_map.json": "303df45a03609e4ead04bc3dc1536d0ab19b5358db685b6f3da123d05ec200e3",
            "tokenizer.json": "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
            "tokenizer_config.json": "acb92769e8195aabd29b7b2137a9e6d6e25c476a4f15aa4355c233426c61576b",
            "vocab.txt": "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
        },
        # The Normalize module has no weights but sentence-transformers expects its folder.
        "empty_dirs": ["2_Normalize"],
    },
    {
        "name": "faster-whisper base.en (speech to text)",
        "subdir": "faster-whisper-base.en",
        "repo": "Systran/faster-whisper-base.en",
        "revision": "3d3d5dee26484f91867d81cb899cfcf72b96be6c",
        "files": {
            "config.json": "f3bc3821e9fc76a27bae538e11ae5b677dcdd352b4600429ce7951d398569aeb",
            "model.bin": "2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef",
            "tokenizer.json": "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df",
            "vocabulary.txt": "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf",
        },
    },
]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_valid(path: Path, expected: str) -> bool:
    return path.is_file() and sha256_of(path) == expected


def download(repo: str, revision: str, filename: str, target: Path, staging: Path) -> None:
    # Imported here so --verify works without huggingface_hub, and so the
    # offline switch used by the engine cannot leak into this script.
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from huggingface_hub import hf_hub_download

    staging.mkdir(parents=True, exist_ok=True)
    fetched = Path(
        hf_hub_download(repo, filename, revision=revision, local_dir=str(staging))
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(fetched), str(target))


def install(dest: Path, verify_only: bool) -> bool:
    all_ok = True
    for model in MODELS:
        model_dir = dest / model["subdir"] if model["subdir"] else dest
        print(f"\n{model['name']}")
        for filename, expected in model["files"].items():
            target = model_dir / filename
            if is_valid(target, expected):
                print(f"  ok        {filename}")
                continue
            if verify_only:
                state = "corrupt" if target.exists() else "missing"
                print(f"  {state:<9} {filename}")
                all_ok = False
                continue

            legacy = LEGACY_MODEL_DIR / filename
            if not model["subdir"] and is_valid(legacy, expected):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy, target)
                print(f"  copied    {filename} (from {LEGACY_MODEL_DIR})")
            else:
                print(f"  fetching  {filename} ...")
                download(model["repo"], model["revision"], filename, target, model_dir / ".download")

            if is_valid(target, expected):
                print(f"  verified  {filename}")
            else:
                print(f"  FAILED    {filename}: checksum does not match, removing it")
                target.unlink(missing_ok=True)
                all_ok = False

        for empty in model.get("empty_dirs", []):
            if not verify_only:
                (model_dir / empty).mkdir(parents=True, exist_ok=True)
        shutil.rmtree(model_dir / ".download", ignore_errors=True)
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help=f"models directory (default: {DEFAULT_DEST})")
    parser.add_argument("--verify", action="store_true", help="only check what is installed")
    args = parser.parse_args()

    dest = args.dest.expanduser()
    print(f"Models directory: {dest}")
    ok = install(dest, args.verify)
    print("\nAll models present and verified." if ok else "\nSome models are missing or failed verification.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
