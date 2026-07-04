# agents/news_template.py

from pathlib import Path
from PIL import Image, ImageDraw

from agents.theme import COLORS
from agents.fonts import get_font
from agents.typography import (
    get_headline_font,
    get_summary_font,
)
from agents.text_layout import (
    wrap_headline,
    calculate_layout,
)

WIDTH = 1280
HEIGHT = 720

OUTPUT_DIR = Path("outputs/graphics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def create_news_template(news):

    img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background_dark"])
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle((0, 0, WIDTH, 90), fill="#b00020")

    logo_font = get_font(36)
    draw.text(
        (40, 25),
        "BAHUVU NEWS",
        font=logo_font,
        fill=COLORS["text_white"],
    )

    # Fonts
    headline_font = get_headline_font(news["title"])
    summary_font = get_summary_font(news["summary"])

    # Wrap headline
    headline = wrap_headline(news["title"])

    # Automatic layout
    layout = calculate_layout(
        draw,
        headline,
        news["summary"],
        headline_font,
        summary_font,
    )

    # Draw headline
    draw.multiline_text(
        (layout["headline_x"], layout["headline_y"]),
        headline,
        font=headline_font,
        fill=COLORS["text_white"],
        spacing=8,
    )

    # Draw summary
    draw.multiline_text(
        (layout["summary_x"], layout["summary_y"]),
        news["summary"],
        font=summary_font,
        fill=COLORS["text_light"],
        spacing=6,
    )

    # Image placeholder
    draw.rounded_rectangle(
        (820, 130, 1220, 560),
        radius=25,
        outline=COLORS["text_light"],
        width=3,
    )

    placeholder_font = get_font(26)

    draw.text(
        (955, 335),
        "NEWS IMAGE",
        font=placeholder_font,
        fill=COLORS["text_light"],
    )

    return img


if __name__ == "__main__":

    sample_news = {
        "title": "Heavy Rain Continues Across Andhra Pradesh",
        "summary": (
            "Officials advise people to stay alert as heavy rainfall "
            "continues in several districts."
        ),
        "category": "WEATHER",
    }

    image = create_news_template(sample_news)
    image.save(OUTPUT_DIR / "news_template.png")

    print("Created news_template.png")