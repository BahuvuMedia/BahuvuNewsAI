# agents/category_badge.py

"""
BahuvuNewsAI
Category Badge Engine
"""

from PIL import ImageDraw

from agents.fonts import get_font
from agents.theme import COLORS


def draw_category_badge(
    draw: ImageDraw.ImageDraw,
    category: str,
    x: int,
    y: int,
):
    """
    Draw the category label.
    """

    font = get_font(26)

    bbox = draw.textbbox((0, 0), category, font=font)

    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]

    padding_x = 12
    padding_y = 6

    draw.rounded_rectangle(
        (
            x,
            y,
            x + width + padding_x * 2,
            y + height + padding_y * 2,
        ),
        radius=8,
        fill=COLORS["accent_yellow"],
    )

    draw.text(
        (
            x + padding_x,
            y + padding_y,
        ),
        category,
        font=font,
        fill="#000000",
    )