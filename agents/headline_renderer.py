# agents/headline_renderer.py

"""
BahuvuNewsAI - Headline Renderer

Compatible with existing project code.
Uses the new Professional Text Engine internally.
"""

try:
    from agents.fonts import get_font
except Exception:
    from PIL import ImageFont

    def get_font(size, bold=False):
        return ImageFont.load_default()


from agents.text_engine import (
    text_width,
    text_height,
    wrap_text,
    fit_text_block,
)


def text_size(draw, text, font):
    return text_width(draw, text, font), text_height(draw, text, font)


def fit_headline(draw, text, max_width, max_lines=3):
    font, lines, size = fit_text_block(
        draw=draw,
        text=text,
        max_width=max_width,
        max_height=220,
        start_size=74,
        min_size=38,
        line_spacing=14,
        max_lines=max_lines,
    )

    return font, lines


def draw_headline(draw, text, x, y, max_width, fill=(255, 255, 255)):
    font, lines = fit_headline(draw, text, max_width)

    line_gap = 14
    current_y = y

    for line in lines:
        draw.text((x + 3, current_y + 3), line, font=font, fill=(0, 0, 0))
        draw.text((x, current_y), line, font=font, fill=fill)

        current_y += text_height(draw, line, font) + line_gap

    return current_y