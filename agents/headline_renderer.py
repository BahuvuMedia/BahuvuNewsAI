# agents/headline_renderer.py

from PIL import ImageDraw

try:
    from agents.fonts import get_font
except Exception:
    from PIL import ImageFont

    def get_font(size, bold=False):
        return ImageFont.load_default()


def text_size(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = word if not current else current + " " + word
        width, _ = text_size(draw, test, font)

        if width <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def fit_headline(draw, text, max_width, max_lines=3):
    for size in range(74, 38, -2):
        font = get_font(size, bold=True)
        lines = wrap_text(draw, text, font, max_width)

        if len(lines) <= max_lines:
            return font, lines

    font = get_font(38, bold=True)
    lines = wrap_text(draw, text, font, max_width)
    return font, lines[:max_lines]


def draw_headline(draw, text, x, y, max_width, fill=(255, 255, 255)):
    font, lines = fit_headline(draw, text, max_width)

    line_gap = 14
    current_y = y

    for line in lines:
        draw.text((x + 3, current_y + 3), line, font=font, fill=(0, 0, 0))
        draw.text((x, current_y), line, font=font, fill=fill)

        _, h = text_size(draw, line, font)
        current_y += h + line_gap

    return current_y