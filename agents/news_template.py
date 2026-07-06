# agents/news_template.py

from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw

from agents.theme import COLORS
from agents.fonts import get_font
from agents.typography import get_headline_font, get_summary_font
from agents.image_loader import load_news_image, resize_and_crop
from agents.broadcast_layout import (
    WIDTH,
    HEIGHT,
    IMAGE_X,
    IMAGE_Y,
    IMAGE_W,
    IMAGE_H,
    HEADLINE_X,
    HEADLINE_Y,
    HEADLINE_W,
    SUMMARY_X,
    SUMMARY_W,
)
from agents.header import draw_header
from agents.category_badge import draw_category_badge


OUTPUT_DIR = Path("outputs/graphics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    line = ""

    for word in words:
        test_line = f"{line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)

        if bbox[2] <= max_width:
            line = test_line
        else:
            if line:
                lines.append(line)
            line = word

    if line:
        lines.append(line)

    return lines


def create_news_template(news):
    img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background_dark"])
    draw = ImageDraw.Draw(img)

    # Background
    for y in range(HEIGHT):
        shade = int(18 + (y / HEIGHT) * 18)
        draw.line((0, y, WIDTH, y), fill=(shade, shade, shade + 8))

    # Header
    draw_header(draw)

    logo_font = get_font(38)
    draw.text((42, 24), "BAHUVU NEWS", font=logo_font, fill="white")

    time_font = get_font(22)
    now = datetime.now().strftime("%d %b %Y")
    draw.text((WIDTH - 210, 34), now, font=time_font, fill="white")

    # Main image
    news_img = load_news_image(news.get("image"))

    if news_img:
        news_img = resize_and_crop(news_img, IMAGE_W, IMAGE_H)
        img.paste(news_img, (IMAGE_X, IMAGE_Y))
    else:
        draw.rectangle(
            (IMAGE_X, IMAGE_Y, IMAGE_X + IMAGE_W, IMAGE_Y + IMAGE_H),
            fill="#333333",
        )

    draw.rectangle(
        (IMAGE_X - 3, IMAGE_Y - 3, IMAGE_X + IMAGE_W + 3, IMAGE_Y + IMAGE_H + 3),
        outline="#ffcc00",
        width=3,
    )

    # Category badge
    draw_category_badge(
        draw,
        news.get("category", "BREAKING NEWS"),
        x=HEADLINE_X,
        y=126,
    )

    # Headline
    headline = news.get("title", "")
    headline_font = get_headline_font(headline)

    headline_lines = wrap_text(draw, headline, headline_font, HEADLINE_W)
    headline_lines = headline_lines[:3]

    y = HEADLINE_Y
    for line in headline_lines:
        draw.text((HEADLINE_X, y), line, font=headline_font, fill="white")
        y += 58

    # Summary
    summary = news.get("summary", "")
    summary_font = get_summary_font(summary)

    summary_y = y + 25
    summary_lines = wrap_text(draw, summary, summary_font, SUMMARY_W)
    summary_lines = summary_lines[:4]

    sy = summary_y
    for line in summary_lines:
        draw.text((SUMMARY_X, sy), line, font=summary_font, fill="#dddddd")
        sy += 36

    # Footer ticker
    footer_y = HEIGHT - 78
    draw.rectangle((0, footer_y, WIDTH, HEIGHT), fill="#111111")
    draw.rectangle((0, footer_y, WIDTH, footer_y + 5), fill="#ffcc00")

    ticker_font = get_font(25)
    ticker = "BREAKING UPDATES  •  BAHUVU NEWS  •  TELUGU NEWS  •  DIGITAL NEWSROOM"
    draw.text((42, footer_y + 26), ticker, font=ticker_font, fill="white")

    output_path = OUTPUT_DIR / "news_template.png"
    img.save(output_path)

    print(f"Created: {output_path}")
    return output_path


if __name__ == "__main__":
    sample_news = {
        "title": "India announces major new technology plan for digital news and artificial intelligence",
        "summary": "The government has announced new steps to support innovation, digital infrastructure and artificial intelligence development across the country.",
        "category": "Technology",
        "image": "assets/images/sample.jpg",
    }

    create_news_template(sample_news)