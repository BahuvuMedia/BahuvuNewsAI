# agents/overlay_effects.py

from PIL import Image, ImageDraw


def add_vertical_gradient(image, top_alpha=0, bottom_alpha=180):
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    width, height = image.size

    for y in range(height):
        alpha = int(top_alpha + (bottom_alpha - top_alpha) * (y / height))
        draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    return Image.alpha_composite(image.convert("RGBA"), overlay)


def add_left_text_shadow(image, width_ratio=0.55, alpha=170):
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    width, height = image.size
    shadow_width = int(width * width_ratio)

    for x in range(shadow_width):
        fade = int(alpha * (1 - x / shadow_width))
        draw.line([(x, 0), (x, height)], fill=(0, 0, 0, fade))

    return Image.alpha_composite(image.convert("RGBA"), overlay)


def add_bottom_news_band(image, band_height=190, alpha=210):
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    width, height = image.size
    y1 = height - band_height

    draw.rectangle((0, y1, width, height), fill=(0, 0, 0, alpha))

    return Image.alpha_composite(image.convert("RGBA"), overlay)