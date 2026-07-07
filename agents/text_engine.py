# agents/text_engine.py

"""
BahuvuNewsAI - Professional Text Engine
"""

from PIL import ImageDraw

try:
    from agents.fonts import get_font
except Exception:
    from PIL import ImageFont

    def get_font(size):
        return ImageFont.load_default()


def safe_get_font(size, bold=False):
    try:
        return get_font(size, bold=bold)
    except TypeError:
        return get_font(size)


def text_bbox(draw: ImageDraw.ImageDraw, text: str, font):
    return draw.textbbox((0, 0), text, font=font)


def text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    box = text_bbox(draw, text, font)
    return box[2] - box[0]


def text_height(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    box = text_bbox(draw, text, font)
    return box[3] - box[1]


def wrap_text(draw, text, font, max_width):
    if not text:
        return []

    words = str(text).split()
    lines = []
    current = ""

    for word in words:
        test_line = word if not current else current + " " + word

        if text_width(draw, test_line, font) <= max_width:
            current = test_line
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def block_height(draw, lines, font, line_spacing=10):
    if not lines:
        return 0

    line_h = text_height(draw, "Ay", font)
    return len(lines) * line_h + (len(lines) - 1) * line_spacing


def fit_text_block(
    draw,
    text,
    max_width,
    max_height,
    start_size,
    min_size=22,
    line_spacing=10,
    max_lines=None,
    bold=False,
):
    size = start_size

    while size >= min_size:
        font = safe_get_font(size, bold=bold)
        lines = wrap_text(draw, text, font, max_width)

        if max_lines is not None and len(lines) > max_lines:
            size -= 2
            continue

        height = block_height(draw, lines, font, line_spacing)

        if height <= max_height:
            return font, lines, size

        size -= 2

    font = safe_get_font(min_size, bold=bold)
    lines = wrap_text(draw, text, font, max_width)

    if max_lines is not None:
        lines = lines[:max_lines]

        if lines:
            last = lines[-1]
            while text_width(draw, last + "...", font) > max_width and len(last) > 3:
                last = last[:-1]
            lines[-1] = last.rstrip() + "..."

    return font, lines, min_size


def draw_text_lines(
    draw,
    lines,
    x,
    y,
    font,
    fill,
    line_spacing=10,
):
    current_y = y
    line_h = text_height(draw, "Ay", font)

    for line in lines:
        draw.text((x, current_y), line, font=font, fill=fill)
        current_y += line_h + line_spacing

    return current_y