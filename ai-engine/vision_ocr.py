"""Text recognition with Apple's Vision framework (macOS).

VNRecognizeTextRequest at the accurate level with language correction, run
in-process through PyObjC. Used as the fallback when the Accessibility API
gives no usable text (ADR 0009). It replaced Tesseract after a comparison on
this Mac: see scripts/compare_ocr.py and the Phase 4 pull request.
"""

import io

from PIL import Image


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
            lines.append((1 - box.origin.y - box.size.height, box.origin.x, candidate[0].string()))
    # Reading order: top to bottom, then left to right.
    lines.sort(key=lambda item: (round(item[0], 2), item[1]))
    return "\n".join(text for _, _, text in lines)
