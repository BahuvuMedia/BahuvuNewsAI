# agents/summary_renderer.py

"""
BahuvuNewsAI - Summary Renderer
Version: v1.1 Broadcast Summary Layout

Clean summary wrapping without ugly truncation.
"""

from agents.fonts import get_font


def measure_text(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_summary(draw, text, font, max_width):
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


def draw_summary(draw, text, x, y, max_width, max_lines=4):
    font = get_font(30)
    line_gap = 12

    lines = wrap_summary(draw, text, font, max_width)
    lines = lines[:max_lines]

    current_y = y

    for line in lines:
        draw.text(
            (x, current_y),
            line,
            font=font,
            fill=(225, 225, 225),
        )

        _, line_height = measure_text(draw, line, font)
        current_y += line_height + line_gap

    return current_y