"""
BahuvuNewsAI - Image Engine
Version: 0.7

This module prepares news images before they are used
by the final graphic generator.
"""

from pathlib import Path
from PIL import Image

# -------------------------------------------------
# Directories
# -------------------------------------------------

ASSETS_DIR = Path("assets")
IMAGES_DIR = ASSETS_DIR / "images"
OUTPUT_DIR = Path("outputs") / "images"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# -------------------------------------------------
# Utility Functions
# -------------------------------------------------

def load_image(image_path):
    """
    Load an image and convert it to RGB mode.
    """
    image = Image.open(image_path)
    return image.convert("RGB")


def resize_image(image, width, height):
    """
    Resize image while maintaining high quality.
    """
    return image.resize((width, height), Image.LANCZOS)


def save_image(image, output_path):
    """
    Save image as PNG.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")


# -------------------------------------------------
# Main Test
# -------------------------------------------------

if __name__ == "__main__":
    print("=" * 40)
    print("BahuvuNewsAI Image Engine")
    print("=" * 40)
    print("Status : Ready")
    print(f"Assets : {IMAGES_DIR}")
    print(f"Outputs: {OUTPUT_DIR}")