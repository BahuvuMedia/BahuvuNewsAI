# agents/renderer.py

from PIL import Image, ImageDraw
from agents.theme import COLORS, LAYOUT
from agents.layout import MEDIA_PANEL, HEADLINE_PANEL, LOGO_BOX
from agents.themes import get_theme
from agents.fonts import get_font
from agents.config import GRAPHICS_DIR, CHANNEL_NAME

GRAPHICS_DIR.mkdir(parents=True, exist_ok=True)

WIDTH = LAYOUT["width"]
HEIGHT = LAYOUT["height"]


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    line = ""

    for word in words:
        test_line = line + word + " "
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] <= max_width:
            line = test_line
        else:
            lines.append(line.strip())
            line = word + " "

    if line:
        lines.append(line.strip())

    return lines


def draw_wrapped_text(draw, x, y, text, font, fill, max_width, line_spacing=15):
    lines = wrap_text(draw, text, font, max_width)

    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=font)
        y += (bbox[3] - bbox[1]) + line_spacing

    return y


def render_news_frame(
    category="GENERAL",
    headline="Bahuvu News Headline",
    summary="News summary will appear here.",
    output_path=None,
):
    theme = get_theme(category)

    if output_path is None:
        output_path = GRAPHICS_DIR / "rendered_news_frame.png"

    img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background_dark"])
    draw = ImageDraw.Draw(img)

    for y in range(HEIGHT):
        shade = int(25 + (y / HEIGHT) * 35)
        draw.line([(0, y), (WIDTH, y)], fill=(5, 18, shade))

    draw.rectangle([0, 0, WIDTH, 110], fill=theme["primary"])
    draw.text((60, 35), theme["label"], font=get_font("medium"), fill=COLORS["text_white"])

    draw.rectangle(
        [LOGO_BOX["x1"], LOGO_BOX["y1"], LOGO_BOX["x2"], LOGO_BOX["y2"]],
        outline=COLORS["text_white"],
        width=3,
    )
    draw.text((1625, 43), CHANNEL_NAME, font=get_font("small"), fill=COLORS["text_white"])

    draw.rounded_rectangle(
        [MEDIA_PANEL["x1"], MEDIA_PANEL["y1"], MEDIA_PANEL["x2"], MEDIA_PANEL["y2"]],
        radius=LAYOUT["corner_radius"],
        fill=COLORS["panel_blue"],
        outline=theme["primary"],
        width=4,
    )
    draw.text((470, 480), "PHOTO / VIDEO AREA", font=get_font("medium"), fill=COLORS["text_muted"])

    draw.rounded_rectangle(
        [
            HEADLINE_PANEL["x1"],
            HEADLINE_PANEL["y1"],
            HEADLINE_PANEL["x2"],
            HEADLINE_PANEL["y2"],
        ],
        radius=LAYOUT["corner_radius"],
        fill=COLORS["panel_dark"],
        outline=theme["accent"],
        width=4,
    )

    panel_x = HEADLINE_PANEL["x1"] + 50
    panel_y = HEADLINE_PANEL["y1"] + 70
    panel_width = HEADLINE_PANEL["x2"] - HEADLINE_PANEL["x1"] - 100

    next_y = draw_wrapped_text(
        draw,
        panel_x,
        panel_y,
        headline,
        get_font("large"),
        COLORS["text_white"],
        panel_width,
        line_spacing=20,
    )

    draw_wrapped_text(
        draw,
        panel_x,
        next_y + 40,
        summary,
        get_font("medium"),
        COLORS["text_light"],
        panel_width,
        line_spacing=15,
    )

    draw.rectangle([0, 890, WIDTH, HEIGHT], fill="#020617")
    draw.rectangle([0, 890, 380, HEIGHT], fill=theme["primary"])
    draw.text((50, 955), theme["icon"] + " LATEST", font=get_font("medium"), fill=COLORS["text_white"])

    draw_wrapped_text(
        draw,
        430,
        955,
        summary,
        get_font("medium"),
        COLORS["text_white"],
        1350,
        line_spacing=10,
    )

    img.save(output_path)
    return output_path


if __name__ == "__main__":
    path = render_news_frame(
        category="WEATHER",
        headline="Heavy Rain Across Andhra Pradesh, Telangana and Coastal Districts",
        summary="IMD has issued alerts for several districts as monsoon activity intensifies across the region.",
    )
    print(f"Created: {path}")