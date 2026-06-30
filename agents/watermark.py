import os

from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip

from agents.branding import (
    CHANNEL_NAME_ENGLISH,
    CHANNEL_NAME_TELUGU,
    PRIMARY_RED,
    SECONDARY_GOLD,
    WHITE,
    WATERMARK_INTERVAL,
    WATERMARK_MARGIN_X,
    WATERMARK_MARGIN_Y,
)


def hex_to_rgba(hex_color, alpha=255):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


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


def create_watermark_image(text, filename):
    width = 300
    height = 110

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    red = hex_to_rgba(PRIMARY_RED, 190)
    gold = hex_to_rgba(SECONDARY_GOLD, 230)
    white = hex_to_rgba(WHITE, 230)

    draw.rounded_rectangle((0, 0, width, height), radius=18, fill=red)

    main_font = get_font(42)
    news_font = get_font(30)

    draw.text((20, 12), text, font=main_font, fill=gold)
    draw.text((95, 62), "NEWS", font=news_font, fill=white)

    img.save(filename)


def create_rotating_watermark_clips(video_width, duration, output_dir):
    telugu_logo = os.path.join(output_dir, "watermark_telugu.png")
    english_logo = os.path.join(output_dir, "watermark_english.png")

    create_watermark_image(CHANNEL_NAME_TELUGU, telugu_logo)
    create_watermark_image(CHANNEL_NAME_ENGLISH, english_logo)

    clips = []

    start = 0
    count = 0

    while start < duration:
        logo_file = telugu_logo if count % 2 == 0 else english_logo

        clip = (
            ImageClip(logo_file)
            .with_start(start)
            .with_duration(min(WATERMARK_INTERVAL, duration - start))
            .with_position((video_width - 330, WATERMARK_MARGIN_Y))
        )

        clips.append(clip)

        start += WATERMARK_INTERVAL
        count += 1

    return clips