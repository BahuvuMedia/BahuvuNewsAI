# agents/footer.py

from datetime import datetime

try:
    from agents.fonts import get_font
except Exception:
    from PIL import ImageFont

    def get_font(size, bold=False):
        return ImageFont.load_default()


def draw_footer(draw, width, height, category="NEWS"):
    red = (180, 0, 28)
    white = (255, 255, 255)
    yellow = (255, 204, 0)

    footer_h = 72
    y = height - footer_h

    draw.rectangle((0, y, width, height), fill=red)

    font_big = get_font(30, bold=True)
    font_small = get_font(24)

    draw.text((40, y + 18), "BAHUVU NEWS", font=font_big, fill=white)

    draw.rectangle((300, y, 560, height), fill=(30, 30, 35))
    draw.text((325, y + 21), category.upper(), font=font_small, fill=yellow)

    now = datetime.now().strftime("%d %b %Y")
    draw.text((width - 260, y + 21), now, font=font_small, fill=white)