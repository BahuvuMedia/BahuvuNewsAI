# agents/text_layout.py

"""
Text Layout Engine
BahuvuNewsAI v0.5
"""

import textwrap
from PIL import ImageDraw

# ==========================================================
# HEADLINE WRAPPING
# ==========================================================

DEFAULT_WIDTH = 22


def wrap_headline(text, width=DEFAULT_WIDTH):
    """
    Wrap long headlines into multiple lines.
    """

    if not text:
        return ""

    # Remove extra spaces
    text = " ".join(text.split())

    return textwrap.fill(text, width=width)


# ==========================================================
# SAFE LAYOUT SETTINGS
# ==========================================================

LEFT_MARGIN = 120
RIGHT_MARGIN = 120

TOP_MARGIN = 180

HEADLINE_GAP = 40
SUMMARY_GAP = 45

LINE_SPACING = 8


# ==========================================================
# TEXT MEASUREMENT
# ==========================================================

def measure_multiline(draw, text, font, spacing=LINE_SPACING):
    """
    Measure multiline text.
    Returns (width, height)
    """

    bbox = draw.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        spacing=spacing,
        align="left"
    )

    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]

    return width, height


# ==========================================================
# AUTOMATIC LAYOUT
# ==========================================================

def calculate_layout(
    draw,
    headline,
    summary,
    headline_font,
    summary_font,
):
    """
    Calculate text positions automatically.
    """

    _, headline_height = measure_multiline(
        draw,
        headline,
        headline_font,
    )

    _, summary_height = measure_multiline(
        draw,
        summary,
        summary_font,
    )

    headline_x = LEFT_MARGIN
    headline_y = TOP_MARGIN

    summary_x = LEFT_MARGIN
    summary_y = (
        headline_y
        + headline_height
        + HEADLINE_GAP
    )

    return {
        "headline_x": headline_x,
        "headline_y": headline_y,
        "summary_x": summary_x,
        "summary_y": summary_y,
        "headline_height": headline_height,
        "summary_height": summary_height,
    }


# ==========================================================
# TEST
# ==========================================================

if __name__ == "__main__":

    sample = (
        "HEAVY RAINS EXPECTED ACROSS ANDHRA PRADESH "
        "AND TELANGANA THIS WEEK CAUSING FLOODING"
    )

    print("Wrapped Headline:\n")
    print(wrap_headline(sample))