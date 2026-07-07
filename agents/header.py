# agents/header.py

"""
BahuvuNewsAI
Broadcast Header Engine
"""

from PIL import ImageDraw

from agents.theme import COLORS
from agents.layout import WIDTH, HEADER_HEIGHT
from agents.fonts import get_font
CHANNEL_NAME = "BAHUVU NEWS"


def draw_header(draw: ImageDraw.ImageDraw):
    """
    Draw the top news header.
    """

    # Header background
    draw.rectangle(
        (0, 0, WIDTH, HEADER_HEIGHT),
        fill=COLORS["breaking_red"],
    )

    # Channel name
    logo_font = get_font(36)

    draw.text(
        (40, 25),
        CHANNEL_NAME,
        font=logo_font,
        fill=COLORS["text_white"],
    )