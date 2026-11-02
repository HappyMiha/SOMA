import numpy as np
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
import pytest

from soma.core import ScreenFrame
from soma.vision import ScreenReader, describe


def frame_with_text():
    image = Image.new("RGB", (1200, 400), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 32)
    except OSError:
        pytest.skip("No Cyrillic-capable font on this machine")
    draw.text((40, 40), "Привіт! Як твої справи?", fill="black", font=font)
    draw.text((40, 200), "Write a message", fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return ScreenFrame(buffer.getvalue(), 1200, 400)


def test_reads_ukrainian_and_english_with_positions_offline():
    reader = ScreenReader()
    if not reader.available:
        pytest.skip("OCR runtime not installed")
    lines = reader.read(frame_with_text())
    texts = [line["text"] for line in lines]
    assert any("Як твої справи" in t for t in texts) and any("Write a message" in t for t in texts)
    first = next(line for line in lines if "справи" in line["text"])
    x0, y0, x1, y1 = first["box"]
    assert 0 <= x0 < x1 <= 1 and y0 < 0.3       # top line, normalized box
    assert describe(lines, "per_mille")[0].split(" ", 1)[0].count(",") == 1


def screen(lines, offset=0):
    image = Image.new("RGB", (1200, 600), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 26)
    except OSError:
        pytest.skip("No Cyrillic-capable font on this machine")
    for i, text in enumerate(lines):
        draw.text((40, 30 + offset + 60 * i), text, fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return ScreenFrame(buffer.getvalue(), 1200, 600)


CHAT = ["Привіт! Як справи?", "Все добре, дякую", "Що робиш сьогодні?"]


def test_only_what_changed_is_read_again():
    reader = ScreenReader()
    if not reader.available:
        pytest.skip("OCR runtime not installed")
    first = [l["text"] for l in reader.read(screen(CHAT))]
    assert len(first) == 3
    recognized = reader.stats["recognized"]
    # The same pixels in a new frame: nothing is detected or recognized again.
    assert [l["text"] for l in reader.read(screen(CHAT))] == first
    assert reader.stats["unchanged"] == 1 and reader.stats["recognized"] == recognized
    # A new message arrives: only that region is read; old lines are kept as read.
    lines = reader.read(screen(CHAT + ["Пишу тобі лист"]))
    assert [l["text"] for l in lines][:3] == first and "лист" in lines[3]["text"]
    assert reader.stats["partial"] == 1 and reader.stats["recognized"] == recognized + 1
    # Scrolling moves every line: they are found again but not re-recognized.
    lines = reader.read(screen(CHAT + ["Пишу тобі лист"], offset=-23))
    assert len(lines) == 4 and reader.stats["recognized"] == recognized + 1
    assert lines[0]["box"][1] < 0.04


def test_a_changed_word_inside_a_line_rereads_the_whole_line():
    reader = ScreenReader()
    if not reader.available:
        pytest.skip("OCR runtime not installed")
    reader.read(screen(CHAT))
    lines = reader.read(screen(["Привіт! Як справи?", "Все погано, дякую", "Що робиш сьогодні?"]))
    assert [l["text"] for l in lines][1] == "Все погано, дякую"
    assert len(lines) == 3


def test_description_uses_the_clicking_coordinate_space():
    lines = [{"text": "Send", "score": .9, "box": (.5, .9, .6, .95)}]
    assert describe(lines, "per_mille") == ["550,925 Send"]
    assert describe(lines, "normalized") == ["0.550,0.925 Send"]
