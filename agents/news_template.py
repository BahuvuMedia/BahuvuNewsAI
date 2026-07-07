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
        text_width = bbox[2] - bbox[0]

        if text_width <= max_width:
            line = test_line
        else:
            if line:
                lines.append(line)
            line = word

    if line:
        lines.append(line)

    return lines


def draw_background(draw):
    for y in range(HEIGHT):
        shade = int(16 + (y / HEIGHT) * 24)
        draw.line((0, y, WIDTH, y), fill=(shade, shade, shade + 8))


def draw_branding(draw):
    logo_font = get_font(38)
    draw.text((42, 24), "BAHUVU NEWS", font=logo_font, fill="white")

    time_font = get_font(22)
    now = datetime.now().strftime("%d %b %Y")
    draw.text((WIDTH - 250, 34), now, font=time_font, fill="white")


def draw_main_image(draw, canvas, image_path):
    news_img = load_news_image(image_path)

    if news_img:
        news_img = resize_and_crop(news_img, IMAGE_W, IMAGE_H)
        canvas.paste(news_img, (IMAGE_X, IMAGE_Y))
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


def draw_headline_block(draw, headline):
    headline_font = get_headline_font(headline)
    headline_lines = wrap_text(draw, headline, headline_font, HEADLINE_W)[:3]

    y = HEADLINE_Y

    for line in headline_lines:
        draw.text((HEADLINE_X + 2, y + 2), line, font=headline_font, fill="#000000")
        draw.text((HEADLINE_X, y), line, font=headline_font, fill="white")
        y += 58

    return y


def draw_summary_block(draw, summary, start_y):
    if not summary:
        return

    summary_font = get_summary_font(summary)
    summary_lines = wrap_text(draw, summary, summary_font, SUMMARY_W)[:4]

    y = start_y + 25

    for line in summary_lines:
        draw.text((SUMMARY_X, y), line, font=summary_font, fill="#dddddd")
        y += 36


def draw_footer_ticker(draw):
    footer_y = HEIGHT - 78

    draw.rectangle((0, footer_y, WIDTH, HEIGHT), fill="#111111")
    draw.rectangle((0, footer_y, WIDTH, footer_y + 5), fill="#ffcc00")

    ticker_font = get_font(25)
    ticker = "BREAKING UPDATES  •  BAHUVU NEWS  •  TELUGU NEWS  •  DIGITAL NEWSROOM"

    draw.text((42, footer_y + 26), ticker, font=ticker_font, fill="white")


def create_news_template(news):
    img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background_dark"])
    draw = ImageDraw.Draw(img)

    draw_background(draw)

    draw_header(draw)
    draw_branding(draw)

    draw_main_image(
        draw=draw,
        canvas=img,
        image_path=news.get("image") or news.get("image_path"),
    )

    draw_category_badge(
        draw,
        news.get("category", "BREAKING NEWS"),
        x=HEADLINE_X,
        y=126,
    )

    headline_bottom = draw_headline_block(
        draw,
        news.get("title", "Breaking News Update"),
    )

    draw_summary_block(
        draw,
        news.get("summary", ""),
        headline_bottom,
    )

    draw_footer_ticker(draw)

    output_path = OUTPUT_DIR / "news_template.png"
    img.save(output_path, quality=95)

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