# agents/text_renderer.py

from PIL import ImageDraw
from agents.fonts import get_font


def is_telugu(text):
    for char in text:
        if "\u0C00" <= char <= "\u0C7F":
            return True
    return False


def get_language(text):
    if is_telugu(text):
        return "telugu"
    return "english"


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = current_line + " " + word if current_line else word
        bbox = draw.textbbox((0, 0), test_line, font=font)
        test_width = bbox[2] - bbox[0]

        if test_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def draw_centered_text(draw, text, box, size_name="large", fill="white"):
    x1, y1, x2, y2 = box
    max_width = x2 - x1
    max_height = y2 - y1

    language = get_language(text)
    font = get_font(size_name, language)

    lines = wrap_text(draw, text, font, max_width)

    line_heights = []
    total_height = 0

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        height = bbox[3] - bbox[1]
        line_heights.append(height)
        total_height += height + 10

    total_height -= 10

    y = y1 + (max_height - total_height) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        x = x1 + (max_width - line_width) // 2

        draw.text((x, y), line, font=font, fill=fill)
        y += line_heights[i] + 10