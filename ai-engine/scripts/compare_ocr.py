"""Compare Apple Vision OCR with Tesseract on rendered pages with known text.

    ai-engine/.venv/bin/python ai-engine/scripts/compare_ocr.py IMAGE_DIR

IMAGE_DIR holds NAME.png screenshots and NAME.html pages they were rendered
from (headless Chrome, 2x scale, like a Retina screen). Word accuracy is the
share of the page's words found by OCR (multiset recall, case-insensitive);
time and CPU are per image, averaged over 3 runs after a warm-up.
"""

import re
import resource
import shutil
import sys
import time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def words(text: str) -> Counter:
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


def recall(truth: Counter, got: Counter) -> float:
    return sum(min(n, got[w]) for w, n in truth.items()) / max(sum(truth.values()), 1)


def cpu_seconds() -> float:
    # Tesseract runs as a child process, Vision in-process; count both.
    total = 0.0
    for who in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN):
        r = resource.getrusage(who)
        total += r.ru_utime + r.ru_stime
    return total


def measure(fn, image):
    fn(image)  # warm-up
    wall, cpu = [], []
    for _ in range(3):
        c, t = cpu_seconds(), time.perf_counter()
        out = fn(image)
        wall.append(time.perf_counter() - t)
        cpu.append(cpu_seconds() - c)
    return out, sum(wall) / 3, sum(cpu) / 3


def main() -> None:
    import pytesseract
    import vision_ocr

    pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract"
    engines = {"vision": vision_ocr.recognize, "tesseract": pytesseract.image_to_string}
    folder = Path(sys.argv[1])
    print(f"{'image':<9} {'engine':<10} {'accuracy':>8} {'time':>8} {'cpu':>8}")
    for png in sorted(folder.glob("*.png")):
        parser = _Text()
        parser.feed((folder / f"{png.stem}.html").read_text())
        truth = words(" ".join(parser.parts))
        retina = Image.open(png).convert("RGB")
        # Also at 1x, as on a non-Retina display or a nominal-resolution grab.
        plain = retina.resize((retina.width // 2, retina.height // 2), Image.LANCZOS)
        for label, image in ((png.stem, retina), (f"{png.stem}@1x", plain)):
            for name, fn in engines.items():
                out, wall, cpu = measure(fn, image)
                print(f"{label:<9} {name:<10} {recall(truth, words(out)):>8.1%} {wall * 1000:>6.0f}ms {cpu * 1000:>6.0f}ms")


if __name__ == "__main__":
    main()
