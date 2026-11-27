# 0009: Text source order: Accessibility first, Apple Vision OCR as the fallback

- **Status:** Accepted
- **Date:** 2026-11-28

## Context

Until Phase 4 every capture was a screenshot of the window, read with
Tesseract. Even with the quality gate from ADR 0006, OCR text is noisy: tab
strips, icons read as punctuation, bookmark bars. Real content that happens
to contain many names and short labels looks like noise to the gate. The
owner's LinkedIn page was dropped at "50% real words". OCR also knows
nothing about where the text came from, so a page's address was never kept.

The app showing the text already knows exactly what it is. macOS exposes
that through the Accessibility API, the same interface screen readers use.

## Decision

**Accessibility first.** When it captures a window, the Rust shell reads the
focused window of the frontmost app through `AXUIElement`:

- In browsers it finds the `AXWebArea` and collects the page's text from
  static text, headings and cells, plus the page URL from `AXURL`.
- In editors, if the focused element is a text area, it takes that
  document's text.
- Otherwise it collects the visible text in the window.
- It asks Electron apps (VS Code, Slack) and Chromium browsers to build their
  accessibility tree (`AXManualAccessibility`, `AXEnhancedUserInterface`),
  which they otherwise skip.
- **Secure text fields are never read.** Elements whose role or subrole is
  secure are skipped along with their subtree, as are menus, toolbars, tab
  groups and scroll bars.
- The walk is bounded: 6,000 elements, 20,000 characters, depth 40, 600 ms,
  and a 250 ms messaging timeout per app, so a slow app cannot stall the
  tracker.

The text, URL and window go to the engine with the capture request. The
engine cleans the text (ADR 0010) and checks it with a lighter gate: at least
8 words and no more than 30 percent symbols. It doesn't require dictionary
words, because names, code and URLs are legitimate. If it passes, the capture
is stored with `text_source = accessibility`.

**Apple Vision OCR as the fallback.** If Accessibility is not allowed, or the
app exposes nothing usable, the engine grabs the window region and reads it
with Apple's Vision framework (`VNRecognizeTextRequest`, accurate level,
language correction), in-process through PyObjC. That text keeps the strict
gate and is stored with `text_source = ocr`. The source is also recorded in
the Capture Ledger ("Read from the app" or "Read from the screen").

**Why Vision, and why PyObjC.** `scripts/compare_ocr.py` compared the two on
pages rendered by headless Chrome at Retina scale and at 1x, with known text:

| page | engine | words found | time | CPU |
|---|---|---|---|---|
| prose | Vision | 100% | 107 ms | 92 ms |
| prose | Tesseract | 100% | 196 ms | 195 ms |
| code | Vision | 96.3% | 98 ms | 87 ms |
| code | Tesseract | 100% | 258 ms | 256 ms |
| profile-style UI | Vision | 100% | 92 ms | 67 ms |
| profile-style UI | Tesseract | 98.4% | 158 ms | 156 ms |
| prose at 1x | Vision | 100% | 78 ms | 74 ms |
| UI at 1x | Vision | 98.4% | 72 ms | 53 ms |
| UI at 1x | Tesseract | 96.9% | 98 ms | 96 ms |

Accuracy is a wash (Tesseract is slightly better on code, Vision on UI text),
but Vision is two to three times faster and uses less CPU. It also ships
with macOS, so the Homebrew Tesseract install is no longer needed. PyObjC
keeps OCR in the engine, next to the screen grab and the gate, instead of
adding a Swift helper binary or Rust Vision bindings to the shell; it adds
about 1 MB to the sidecar. Tesseract is removed from the dependencies.

## Consequences

Captures are the text people actually read, with URLs, and far less noise.
Pages like the LinkedIn profile now pass. OCR still covers apps without
accessibility support and users who decline the permission.

The costs: Engram asks for a third macOS permission, Accessibility, which is
powerful (see docs/threat-model.md for exactly what Engram does with it).
Accessibility text includes some interface labels the clean-up has to deal
with. Chrome builds its accessibility tree lazily, so the very first read
after enabling it can come back empty and fall back to OCR. Vision ties OCR
to macOS, which matches the project's current target.
