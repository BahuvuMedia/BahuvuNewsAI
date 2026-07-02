# agents/graphics_engine.py

from pathlib import Path
from PIL import Image, ImageDraw

from agents.theme import COLORS
from agents.fonts import get_font
from agents.text_renderer import draw_centered_text

WIDTH = 1280
HEIGHT = 720

OUTPUT_DIR = Path("outputs/graphics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def create_canvas(width=WIDTH, height=HEIGHT):
    return Image.new("RGB", (width, height), COLORS["background_dark"])


def create_breaking_news_header():
    img = create_canvas()
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, WIDTH, 130), fill=COLORS["breaking_red"])
    draw.text((40, 25), "BREAKING NEWS", font=get_font("large"), fill=COLORS["text_white"])
    draw.text((40, 88), "తాజా వార్తలు", font=get_font("medium", "telugu"), fill=COLORS["text_white"])

    img.save(OUTPUT_DIR / "breaking_news_header.png")


def create_top_news_header():
    img = create_canvas()
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, WIDTH, 130), fill=COLORS["panel_blue"])
    draw.text((40, 25), "TOP NEWS", font=get_font("large"), fill=COLORS["text_white"])
    draw.text((40, 88), "ముఖ్య వార్తలు", font=get_font("medium", "telugu"), fill=COLORS["text_white"])

    img.save(OUTPUT_DIR / "top_news_header.png")


def create_headline_card():
    img = create_canvas()
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, WIDTH, 100), fill=COLORS["breaking_red"])
    draw.text((40, 22), "BAHUVU NEWS", font=get_font("medium"), fill=COLORS["text_white"])

    draw.rounded_rectangle((70, 180, 1210, 560), radius=35, fill=COLORS["panel_dark"])

    draw_centered_text(
        draw,
        "Major News Headline",
        (120, 230, 1160, 330),
        size_name="headline",
        fill=COLORS["text_white"],
    )

    draw_centered_text(
        draw,
        "ప్రధాన వార్త శీర్షిక",
        (120, 350, 1160, 450),
        size_name="medium",
        fill=COLORS["text_light"],
    )

    img.save(OUTPUT_DIR / "headline_card.png")


def create_quote_card():
    img = create_canvas()
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle((100, 150, 1180, 570), radius=40, fill=COLORS["panel_dark"])

    draw_centered_text(
        draw,
        "News that matters.",
        (140, 220, 1140, 330),
        size_name="headline",
        fill=COLORS["text_white"],
    )

    draw_centered_text(
        draw,
        "ప్రజలకు అవసరమైన వార్తలు",
        (140, 350, 1140, 450),
        size_name="medium",
        fill=COLORS["text_light"],
    )

    img.save(OUTPUT_DIR / "quote_card.png")


def create_thumbnail_template():
    img = create_canvas()
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, WIDTH, 130), fill=COLORS["breaking_red"])
    draw.text((40, 25), "BAHUVU NEWS", font=get_font("large"), fill=COLORS["text_white"])

    draw.rounded_rectangle((70, 190, 1210, 620), radius=40, fill=COLORS["panel_dark"])

    draw_centered_text(
        draw,
        "BIG NEWS",
        (120, 250, 1160, 360),
        size_name="title",
        fill=COLORS["accent_yellow"],
    )

    draw_centered_text(
        draw,
        "పెద్ద వార్త",
        (120, 390, 1160, 500),
        size_name="headline",
        fill=COLORS["text_white"],
    )

    img.save(OUTPUT_DIR / "thumbnail_template.png")


def create_vertical_story_template():
    img = create_canvas(1080, 1920)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, 1080, 190), fill=COLORS["breaking_red"])
    draw.text((60, 55), "BAHUVU NEWS", font=get_font("large"), fill=COLORS["text_white"])

    draw.rounded_rectangle((80, 520, 1000, 1360), radius=45, fill=COLORS["panel_dark"])

    draw_centered_text(
        draw,
        "NEWS UPDATE",
        (120, 660, 960, 780),
        size_name="headline",
        fill=COLORS["accent_yellow"],
    )

    draw_centered_text(
        draw,
        "వార్తా అప్డేట్",
        (120, 820, 960, 940),
        size_name="large",
        fill=COLORS["text_white"],
    )

    img.save(OUTPUT_DIR / "vertical_story_template.png")


def create_end_screen():
    img = create_canvas()
    draw = ImageDraw.Draw(img)

    draw_centered_text(
        draw,
        "THANK YOU",
        (100, 150, 1180, 260),
        size_name="title",
        fill=COLORS["text_white"],
    )

    draw_centered_text(
        draw,
        "Subscribe to BAHUVU NEWS",
        (100, 300, 1180, 390),
        size_name="large",
        fill=COLORS["accent_yellow"],
    )

    draw_centered_text(
        draw,
        "బాహువు న్యూస్‌ను సబ్‌స్క్రైబ్ చేయండి",
        (100, 410, 1180, 500),
        size_name="medium",
        fill=COLORS["text_light"],
    )

    img.save(OUTPUT_DIR / "end_screen.png")


def generate_graphics_pack():
    create_breaking_news_header()
    create_top_news_header()
    create_headline_card()
    create_quote_card()
    create_thumbnail_template()
    create_vertical_story_template()
    create_end_screen()

    print("Graphics Engine completed successfully.")
    print("Created graphics in outputs/graphics")


if __name__ == "__main__":
    generate_graphics_pack()