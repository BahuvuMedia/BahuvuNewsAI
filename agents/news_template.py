# agents/news_template.py

from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw

from agents.theme import COLORS
from agents.fonts import get_font
from agents.broadcast_layout import WIDTH, HEIGHT
from agents.header import draw_header
from agents.category_badge import draw_category_badge
from agents.photo_layout import render_photo
from agents.headline_renderer import draw_headline
from agents.summary_renderer import draw_summary

OUTPUT_DIR = Path("outputs/graphics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FOOTER_HEIGHT = 78
SAFE_RIGHT = 70

TEXT_X = 545
BADGE_Y = 122
HEADLINE_Y = 168
SUMMARY_GAP = 34

TEXT_MAX_WIDTH = WIDTH - TEXT_X - SAFE_RIGHT


def draw_background(draw):
    for y in range(HEIGHT):
        shade = int(14 + (y / HEIGHT) * 26)
        draw.line((0, y, WIDTH, y), fill=(shade, shade, shade + 10))


def draw_branding(draw):
    logo_font = get_font(38)
    draw.text((42, 24), "BAHUVU NEWS", font=logo_font, fill="white")

    date_font = get_font(22)
    today = datetime.now().strftime("%d %b %Y")
    draw.text((WIDTH - 250, 34), today, font=date_font, fill="white")


def draw_footer_ticker(draw):
    footer_y = HEIGHT - FOOTER_HEIGHT

    draw.rectangle((0, footer_y, WIDTH, HEIGHT), fill="#111111")
    draw.rectangle((0, footer_y, WIDTH, footer_y + 5), fill="#ffcc00")

    ticker_font = get_font(25)
    ticker = "BREAKING UPDATES  •  BAHUVU NEWS  •  TELUGU NEWS"

    draw.text((42, footer_y + 26), ticker, font=ticker_font, fill="white")


def create_news_template(news):
    img = Image.new("RGBA", (WIDTH, HEIGHT), COLORS["background_dark"])
    draw = ImageDraw.Draw(img)

    draw_background(draw)
    draw_header(draw)
    draw_branding(draw)

    render_photo(
        draw=draw,
        canvas=img,
        image_path=news.get("image") or news.get("image_path"),
    )

    draw_category_badge(
        draw,
        news.get("category", "GENERAL"),
        x=TEXT_X,
        y=BADGE_Y,
    )

    headline_bottom = draw_headline(
        draw=draw,
        text=news.get("title", "Breaking News Update"),
        x=TEXT_X,
        y=HEADLINE_Y,
        max_width=TEXT_MAX_WIDTH,
        fill=(255, 255, 255),
    )

    summary_y = headline_bottom + SUMMARY_GAP

    draw_summary(
        draw=draw,
        text=news.get("summary", ""),
        x=TEXT_X,
        y=summary_y,
        max_width=TEXT_MAX_WIDTH,
        max_lines=4,
    )

    draw_footer_ticker(draw)

    output_path = OUTPUT_DIR / "news_template.png"
    img.convert("RGB").save(output_path, quality=95)

    print(f"Created: {output_path}")
    return output_path


if __name__ == "__main__":
    sample_news = {
        "title": "India Announces Major New Technology Plan For Digital News And Artificial Intelligence",
        "summary": "The government has announced new steps to support innovation, digital infrastructure and artificial intelligence development across the country.",
        "category": "Technology",
        "image": "assets/images/sample.jpg",
    }

    create_news_template(sample_news)