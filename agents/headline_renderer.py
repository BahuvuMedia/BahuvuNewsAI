# agents/headline_renderer.py

"""
BahuvuNewsAI - Headline Renderer
Version: v1.1 Broadcast Headline Layout
"""

from agents.fonts import get_font


def measure_text(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_headline(draw, text, font, max_width):
    words = str(text).split()
    lines = []
    current = ""

    for word in words:
        test_line = word if not current else current + " " + word
        width, _ = measure_text(draw, test_line, font)

        if width <= max_width:
            current = test_line
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def fit_headline(draw, text, max_width, max_lines=3):
    for size in range(38, 25, -2):
        font = get_font(size)
        lines = wrap_headline(draw, text, font, max_width)

        if len(lines) <= max_lines:
            return font, lines

    font = get_font(26)
    lines = wrap_headline(draw, text, font, max_width)
    return font, lines[:max_lines]


def draw_headline(draw, text, x, y, max_width, fill=(255, 255, 255)):
    font, lines = fit_headline(draw, text, max_width)

    line_gap = 8
    current_y = y

    for line in lines:
        draw.text((x + 2, current_y + 2), line, font=font, fill=(0, 0, 0))
        draw.text((x, current_y), line, font=font, fill=fill)

        _, line_height = measure_text(draw, line, font)
        current_y += line_height + line_gap

    return current_y