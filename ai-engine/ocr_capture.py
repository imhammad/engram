import sys

import mss
import pytesseract
from PIL import Image

from paths import find_tesseract_cmd

_tesseract_cmd = find_tesseract_cmd()
if _tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd
else:
    print("Tesseract not found. Install it with 'brew install tesseract' or set TESSERACT_CMD.")

if sys.platform == "darwin":
    import mss.darwin

    # By default mss asks macOS for a nominal (1x) image, so on a Retina display
    # a window is captured at half its real sharpness. Dropping the
    # NominalResolution flag returns native pixels, which OCR reads far better.
    mss.darwin.IMAGE_OPTIONS = (
        mss.darwin.kCGWindowImageBoundsIgnoreFraming
        | mss.darwin.kCGWindowImageShouldBeOpaque
    )

_MSS = getattr(mss, "MSS", None) or mss.mss


def capture_screen_text(region: dict | None = None) -> str:
    """Grab a screen region (or the primary display) and return its OCR text.

    On macOS, region coordinates are in points: active-win-pos-rs reports window
    bounds in points and mss takes its region in points, so no scaling is
    needed. With the option above the returned image is in native pixels (twice
    the region size on a Retina display).
    """
    if not _tesseract_cmd:
        raise RuntimeError("Tesseract is not installed. Run 'brew install tesseract'.")

    with _MSS() as sct:
        if region:
            monitor = {
                "left": region["x"],
                "top": region["y"],
                "width": region["width"],
                "height": region["height"],
            }
        else:
            monitor = sct.monitors[1]  # fallback: primary monitor, full screen

        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

    text = pytesseract.image_to_string(img)
    return text.strip()
