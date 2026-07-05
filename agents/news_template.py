# agents/news_template.py

from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw

from agents.theme import COLORS
from agents.fonts import get_font
from agents.typography import get_headline_font, get_summary_font
from agents.image_loader import load_news_image, resize_and_crop
from agents.layout import WIDTH, HEIGHT

OUTPUT_DIR = Path("outputs/graphics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def create_news_template(news):
    img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background_dark"])
    draw = ImageDraw.Draw(img)

    # Background
    for y in range(HEIGHT):
        shade = int(18 + (y / HEIGHT) * 18)
        draw.line((0, y, WIDTH, y), fill=(shade, shade, shade + 8))

    # Header
    header_h = 92
    draw.rectangle((0, 0, WIDTH, header_h), fill="#9b0018")
    draw.rectangle((0, header_h - 6, WIDTH, header_h), fill="#ffcc00")

    logo_font = get_font(38)
    draw.text((42, 24), "BAHUVU NEWS", font=logo_font, fill="white")

    time_font = get_font(22)
    now = datetime.now().strftime("%d %b %Y")
    draw.text((WIDTH - 210, 34), now, font=time_font, fill="white")

    # Main image
    image_x = 52
    image_y = 125
    image_w = 500
    image_h = 335

    news_img = load_news_image(news.get("image"))

    if news_img:
        news_img = resize_and_crop(news_img, image_w, image_h)
        img.paste(news_img, (image_x, image_y))
    else:
        draw.rectangle(
            (image_x, image_y, image_x + image_w, image_y + image_h),
            fill="#333333",
        )

    draw.rectangle(
        (image_x - 3, image_y - 3, image_x + image_w + 3, image_y + image_h + 3),
        outline="#ffcc00",
        width=3,
    )

    # Category badge
    category = news.get("category", "BREAKING NEWS")

    badge_x = 590
    badge_y = 126
    badge_w = 300
    badge_h = 48

    draw.rounded_rectangle(
        (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
        radius=10,
        fill="#ffcc00",
    )

    category_font = get_font(20)
    category_text = category.upper()

    bbox = draw.textbbox((0, 0), category_text, font=category_font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    text_x = badge_x + (badge_w - text_w) // 2
    text_y = badge_y + (badge_h - text_h) // 2 - 1

    draw.text(
        (text_x, text_y),
        category_text,
        font=category_font,
        fill="#111111",
    )

    # Headline
    headline = news.get("title", "")
    headline_font = get_headline_font(headline)

    headline_x = 590
    headline_y = 185
    headline_w = 620

    lines = []
    words = headline.split()
    line = ""

    for word in words:
        test_line = f"{line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=headline_font)
        if bbox[2] <= headline_w:
            line = test_line
        else:
            lines.append(line)
            line = word

    if line:
        lines.append(line)

    lines = lines[:3]

    y = headline_y
    for line in lines:
        draw.text((headline_x, y), line, font=headline_font, fill="white")
        y += 58

    # Summary
    summary = news.get("summary", "")
    summary_font = get_summary_font(summary)

    summary_x = 590
    summary_y = y + 25
    summary_w = 610

    summary_lines = []
    words = summary.split()
    line = ""

    for word in words:
        test_line = f"{line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=summary_font)
        if bbox[2] <= summary_w:
            line = test_line
        else:
            summary_lines.append(line)
            line = word

    if line:
        summary_lines.append(line)

    summary_lines = summary_lines[:4]

    sy = summary_y
    for line in summary_lines:
        draw.text((summary_x, sy), line, font=summary_font, fill="#dddddd")
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