# agents/summary_renderer.py

"""
BahuvuNewsAI - Summary Renderer

Compatible with existing project code.
Uses the Professional Text Engine internally.
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


def draw_summary(draw, text, x, y, max_width, max_lines=3):
    font, lines, size = fit_text_block(
        draw=draw,
        text=text,
        max_width=max_width,
        max_height=150,
        start_size=34,
        min_size=24,
        line_spacing=10,
        max_lines=max_lines,
    )

    current_y = y

    for line in lines:
        draw.text((x, current_y), line, font=font, fill=(225, 225, 225))
        current_y += text_height(draw, line, font) + 10

    return current_y