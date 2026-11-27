from text_quality import assess_capture, clean_ocr_text, noise_reason

REAL = (
    "Project kickoff notes\n"
    "The research integrity agent will check every citation against CrossRef\n"
    "before the December review meeting.\n"
)
TAB_STRIP = "'@ OG »- BBE SOKO sOCOsBS CME | CHCOKKOO COR DOCO# FOO iz ki kik © 4 AAQ «x + +"
MENU_BAR = "@ Engram File Edit View Window Help Alor Setar 7 a ? le"


def test_real_content_is_kept():
    text, reason = assess_capture(REAL)
    assert reason is None
    assert "research integrity agent" in text


def test_menu_bar_and_tab_strip_lines_are_removed():
    text, reason = assess_capture(f"{MENU_BAR}\n{TAB_STRIP}\n{REAL}")
    assert reason is None
    assert "File Edit View" not in text
    assert "SOKO" not in text


def test_mostly_noise_capture_is_dropped_even_if_a_line_is_readable():
    noisy = "\n".join([TAB_STRIP] * 6 + ["Personal Research Blogs College Book"])
    _, reason = assess_capture(noisy)
    assert reason is not None and "unreadable" in reason


def test_too_few_words_is_dropped():
    assert "too few" in noise_reason("Save Cancel")


def test_symbol_heavy_text_is_dropped():
    assert noise_reason("Hello there friend, ##### ===== ***** ##### ===== ***** words words more") is not None


def test_clean_keeps_blank_free_output():
    assert clean_ocr_text("\n\n" + REAL + "\n\n") == REAL.strip()
