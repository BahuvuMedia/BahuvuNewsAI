# agents/photo_layout.py

"""
BahuvuNewsAI - Professional Photo Layout Renderer
Version: v1.0
"""

from PIL import Image, ImageDraw, ImageFilter

from agents.layout import PHOTO, CORNER_RADIUS
from agents.image_loader import load_news_image, resize_and_crop


def create_rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (0, 0, size[0], size[1]),
        radius=radius,
        fill=255,
    )
    return mask


def render_photo_shadow(canvas):
    shadow_offset = 10
    shadow_blur = 18

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)

    shadow_box = (
        PHOTO.x + shadow_offset,
        PHOTO.y + shadow_offset,
        PHOTO.x + PHOTO.width + shadow_offset,
        PHOTO.y + PHOTO.height + shadow_offset,
    )

    shadow_draw.rounded_rectangle(
        shadow_box,
        radius=CORNER_RADIUS,
        fill=(0, 0, 0, 150),
    )

    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
    canvas.alpha_composite(shadow)


def render_placeholder(draw):
    draw.rounded_rectangle(
        PHOTO.box,
        radius=CORNER_RADIUS,
        fill=(45, 45, 50),
        outline=(255, 204, 0),
        width=3,
    )

    draw.text(
        (PHOTO.x + 40, PHOTO.y + PHOTO.height // 2 - 20),
        "BAHUVU NEWS IMAGE",
        fill=(220, 220, 220),
    )


def render_photo(draw, canvas, image_path):
    """
    Render professional news photo with:
    - rounded corners
    - soft shadow
    - gold border
    """

    if canvas.mode != "RGBA":
        canvas = canvas.convert("RGBA")

    render_photo_shadow(canvas)

    image = load_news_image(image_path)

    if image is None:
        render_placeholder(draw)
        return

    image = resize_and_crop(image, PHOTO.width, PHOTO.height).convert("RGBA")

    mask = create_rounded_mask(
        (PHOTO.width, PHOTO.height),
        CORNER_RADIUS,
    )

    canvas.paste(
        image,
        (PHOTO.x, PHOTO.y),
        mask,
    )

    render_photo_border(draw)


def render_photo_border(draw):
    draw.rounded_rectangle(
        PHOTO.box,
        radius=CORNER_RADIUS,
        outline=(255, 204, 0),
        width=3,
    )