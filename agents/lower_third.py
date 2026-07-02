from PIL import Image, ImageDraw, ImageFont
import os

from agents.branding import PRIMARY_RED, WHITE


def get_font(size):
    fonts = [
        r"C:\Windows\Fonts\NirmalaB.ttf",
        r"C:\Windows\Fonts\Nirmala.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ]

    for font in fonts:
        if os.path.exists(font):
            return ImageFont.truetype(font, size)

    return ImageFont.load_default()


def create_category_banner(text, output_file):

    width = 1920
    height = 90

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rectangle(
        (0, 0, width, height),
        fill=(213, 0, 0, 215)
    )

    font = get_font(46)

    draw.text(
        (40, 18),
        text,
        font=font,
        fill=(255, 255, 255, 255)
    )

    img.save(output_file)