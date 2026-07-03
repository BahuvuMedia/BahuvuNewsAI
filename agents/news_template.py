# agents/news_template.py

from pathlib import Path
from PIL import Image, ImageDraw

from agents.theme import COLORS
from agents.fonts import get_font

WIDTH = 1280
HEIGHT = 720

OUTPUT_DIR = Path("outputs/graphics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def create_news_template(news):
    img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background_dark"])
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, WIDTH, 90), fill="#b00020")

    logo_font = get_font(36)
    draw.text((40, 25), "BAHUVU NEWS", font=logo_font, fill=COLORS["text_white"])

    headline_font = get_font(56)
    draw.text(
        (60, 150),
        news["title"],
        fill=COLORS["text_white"],
        font=headline_font,
    )

    summary_font = get_font(30)
    draw.text(
        (60, 240),
        news["summary"],
        fill=COLORS["text_light"],
        font=summary_font,
    )

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
        fill=COLORS["text_light"],
        font=placeholder_font,
    )

    return img


if __name__ == "__main__":
    sample_news = {
        "title": "Heavy Rain Continues Across Andhra Pradesh",
        "summary": "Officials advise people to stay alert as heavy rainfall continues in several districts.",
        "category": "WEATHER",
    }

    image = create_news_template(sample_news)
    image.save(OUTPUT_DIR / "news_template.png")
    print("Created news_template.png")