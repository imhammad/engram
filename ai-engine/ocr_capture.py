import sys

import fake_models

# Points from the top of the main display covered by the menu bar, which
# carries no content worth remembering. 38 covers notched MacBook displays.
MENU_BAR_HEIGHT = 38

if not fake_models.enabled():
    import mss
    from PIL import Image

    import vision_ocr

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


def clip_menu_bar(left: int, top: int, width: int, height: int) -> tuple[int, int, int, int]:
    """Trim a region so it does not include the menu bar strip at the top."""
    if sys.platform == "darwin" and top < MENU_BAR_HEIGHT:
        cut = MENU_BAR_HEIGHT - top
        return left, MENU_BAR_HEIGHT, width, max(height - cut, 0)
    return left, top, width, height


def capture_screen_text(region: dict | None = None) -> str:
    """Grab a screen region (or the primary display) and return its OCR text.

    On macOS, region coordinates are in points: active-win-pos-rs reports window
    bounds in points and mss takes its region in points, so no scaling is
    needed. With the option above the returned image is in native pixels (twice
    the region size on a Retina display).
    """
    if fake_models.enabled():
        return fake_models.ocr_text(region)

    with _MSS() as sct:
        if region:
            left, top, width, height = region["x"], region["y"], region["width"], region["height"]
        else:
            full = sct.monitors[1]  # fallback: primary monitor, full screen
            left, top, width, height = full["left"], full["top"], full["width"], full["height"]
        left, top, width, height = clip_menu_bar(left, top, width, height)
        if width <= 0 or height <= 0:
            return ""
        monitor = {"left": left, "top": top, "width": width, "height": height}

        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

    # Apple Vision replaced Tesseract in Phase 4 (ADR 0009).
    return vision_ocr.recognize(img).strip()
