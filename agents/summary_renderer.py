# agents/summary_renderer.py

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


def draw_summary(draw, text, x, y, max_width, max_lines=3):
    font = get_font(34)
    lines = wrap_text(draw, text, font, max_width)[:max_lines]

    current_y = y

    for line in lines:
        draw.text((x, current_y), line, font=font, fill=(225, 225, 225))
        _, h = text_size(draw, line, font)
        current_y += h + 10

    return current_y