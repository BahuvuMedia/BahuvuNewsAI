"""
BahuvuNewsAI - Logo Manager
Version: 0.8

Handles loading, resizing, and positioning of the
BAHUVU NEWS logo for all graphics.
"""

from pathlib import Path
from PIL import Image

# -------------------------------------------------
# Directories
# -------------------------------------------------

ASSETS_DIR = Path("assets")
LOGO_DIR = ASSETS_DIR / "logos"

DEFAULT_LOGO = LOGO_DIR / "bahuvu_logo.png"


# -------------------------------------------------
# Logo Functions
# -------------------------------------------------

def logo_exists():
    """
    Check whether the default logo exists.
    """
    return DEFAULT_LOGO.exists()


def load_logo():
    """
    Load the logo with transparency preserved.
    """
    if not logo_exists():
        raise FileNotFoundError(
            f"Logo not found:\n{DEFAULT_LOGO}"
        )

    return Image.open(DEFAULT_LOGO).convert("RGBA")


def resize_logo(logo, width):
    """
    Resize logo while preserving aspect ratio.
    """
    aspect_ratio = logo.height / logo.width
    height = int(width * aspect_ratio)

    return logo.resize((width, height), Image.LANCZOS)


def paste_logo(background, logo, x, y):
    """
    Paste logo onto another image using transparency.
    """
    background.paste(logo, (x, y), logo)
    return background


# -------------------------------------------------
# Test
# -------------------------------------------------

if __name__ == "__main__":

    print("=" * 40)
    print("BahuvuNewsAI Logo Manager")
    print("=" * 40)

    print(f"Logo path : {DEFAULT_LOGO}")

    if logo_exists():
        logo = load_logo()
        print("Status    : Logo Found")
        print(f"Size      : {logo.width} x {logo.height}")
    else:
        print("Status    : Logo Not Found")
        print("Create:")
        print("assets/logos/bahuvu_logo.png")