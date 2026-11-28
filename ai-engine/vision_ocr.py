"""Text recognition with Apple's Vision framework (macOS).

VNRecognizeTextRequest at the accurate level with language correction, run
in-process through PyObjC. Used as the fallback when the Accessibility API
gives no usable text (ADR 0009). It replaced Tesseract after a comparison on
this Mac: see scripts/compare_ocr.py and the Phase 4 pull request.
"""

from __future__ import annotations

import io

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # Pillow is only needed where Vision runs, not by order_blocks
    from PIL import Image

# Two columns are separate when a vertical strip at least this wide (as a
# share of the image width) has no text crossing it.
MIN_COLUMN_GAP = 0.015


@dataclass
class Line:
    top: float    # 0 at the top of the image, 1 at the bottom
    left: float   # 0 at the left edge, 1 at the right
    right: float
    text: str


def order_blocks(lines: list[Line]) -> list[list[Line]]:
    """Put recognised lines in reading order, column by column.

    Sorting every line by its height on the page interleaves a sidebar with
    the main pane next to it ("Recents / Hello, how can I / Project notes /
    help you today?"). Instead, find vertical gaps that no line crosses,
    treat each strip between gaps as a column, and read each column top to
    bottom, left column first. A line that spans a gap (a full-width title)
    joins the strips into one column, so single-column pages read as before.
    """
    if not lines:
        return []
    spans = sorted((l.left, l.right) for l in lines)
    columns: list[list[float]] = []
    for left, right in spans:
        if columns and left <= columns[-1][1] + MIN_COLUMN_GAP:
            columns[-1][1] = max(columns[-1][1], right)
        else:
            columns.append([left, right])
    blocks: list[list[Line]] = [[] for _ in columns]
    for line in lines:
        centre = (line.left + line.right) / 2
        index = next((i for i, (l, r) in enumerate(columns) if l - 1e-9 <= centre <= r + 1e-9), 0)
        blocks[index].append(line)
    return [sorted(b, key=lambda l: (round(l.top, 3), l.left)) for b in blocks if b]


def recognize(image: Image.Image) -> str:
    """Return the text in an image, one recognised line per line, top to bottom."""
    import Vision  # imported lazily: macOS only, and slow to load
    from Foundation import NSData

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = NSData.dataWithBytes_length_(buffer.getvalue(), len(buffer.getvalue()))

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)

    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision text recognition failed: {error}")

    lines = []
    for observation in request.results() or []:
        candidate = observation.topCandidates_(1)
        if candidate:
            box = observation.boundingBox()  # normalised, origin bottom-left
            top = 1 - box.origin.y - box.size.height
            lines.append(Line(top, box.origin.x, box.origin.x + box.size.width, candidate[0].string()))
    return "\n\n".join("\n".join(line.text for line in block) for block in order_blocks(lines))
