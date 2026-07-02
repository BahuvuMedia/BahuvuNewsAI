# agents/fonts.py

from pathlib import Path
from PIL import ImageFont
from agents.theme import FONT_SIZES

FONTS_DIR = Path("assets/fonts")

FONT_FILES = {
    "english": "arial.ttf",
    "telugu": "NotoSansTelugu-Regular.ttf",
    "telugu_bold": "NotoSansTelugu-Bold.ttf",
}


def get_font(size_name="medium", language="english"):
    size = FONT_SIZES.get(size_name, FONT_SIZES["medium"])
    font_file = FONT_FILES.get(language, FONT_FILES["english"])
    font_path = FONTS_DIR / font_file

    try:
        return ImageFont.truetype(str(font_path), size)
    except:
        return ImageFont.load_default()