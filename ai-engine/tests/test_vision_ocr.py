"""Vision OCR reading order: a sidebar and a main pane must not interleave."""

import sys
from pathlib import Path

import pytest

from vision_ocr import Line, order_blocks


def test_sidebar_and_main_pane_come_out_as_separate_blocks():
    lines = [
        Line(0.10, 0.02, 0.20, "Recents"),
        Line(0.10, 0.30, 0.90, "Hello, how can I help you today?"),
        Line(0.15, 0.02, 0.22, "Project notes"),
        Line(0.15, 0.30, 0.88, "Here is the summary you asked for."),
        Line(0.20, 0.02, 0.18, "Birthday ideas"),
    ]
    blocks = order_blocks(lines)
    assert [[l.text for l in b] for b in blocks] == [
        ["Recents", "Project notes", "Birthday ideas"],
        ["Hello, how can I help you today?", "Here is the summary you asked for."],
    ]


def test_full_width_line_keeps_a_single_column_page_in_order():
    lines = [Line(0.05, 0.05, 0.95, "A title across the page"),
             Line(0.10, 0.05, 0.50, "left words"), Line(0.10, 0.55, 0.95, "right words"),
             Line(0.15, 0.05, 0.90, "Next paragraph line")]
    blocks = order_blocks(lines)
    assert len(blocks) == 1
    assert [l.text for l in blocks[0]] == ["A title across the page", "left words", "right words", "Next paragraph line"]


def test_empty():
    assert order_blocks([]) == []


FONT = "/System/Library/Fonts/Helvetica.ttc"


@pytest.mark.skipif(sys.platform != "darwin" or not Path(FONT).exists(), reason="Apple Vision runs on macOS only")
def test_real_two_column_image_is_read_column_by_column(tmp_path):
    pytest.importorskip("Vision")
    from PIL import Image, ImageDraw, ImageFont

    import vision_ocr

    font = ImageFont.truetype(FONT, 30)
    img = Image.new("RGB", (1400, 520), "white")
    draw = ImageDraw.Draw(img)
    sidebar = ["Recents", "Project notes", "Birthday ideas", "Travel plans"]
    main = ["Hello, how can I help you today?", "Here is the summary you asked for.",
            "The meeting moved to Thursday.", "Room 204 is booked for the review."]
    for i, (a, b) in enumerate(zip(sidebar, main)):
        draw.text((30, 40 + i * 110), a, fill="black", font=font)
        draw.text((420, 40 + i * 110), b, fill="black", font=font)
    text = vision_ocr.recognize(img)
    first_block, second_block = text.split("\n\n")[:2]
    assert "Recents" in first_block and "Travel plans" in first_block
    assert "Hello" in second_block and "Room 204" in second_block
    assert "Recents" not in second_block
