# agents/image_loader.py

from pathlib import Path
from PIL import Image, ImageOps


def load_news_image(image_path):
    print("=" * 50)
    print("Image path received:", image_path)

    if not image_path:
        print("No image path received!")
        return None

    path = Path(image_path)

    print("Resolved path:", path.resolve())
    print("Exists:", path.exists())

    if not path.exists():
        print("Image file NOT FOUND")
        return None

    try:
        image = Image.open(path).convert("RGB")
        print("Image loaded successfully")
        return image
    except Exception as e:
        print("PIL Error:", e)
        return None


def resize_and_crop(image, target_width, target_height):
    return ImageOps.fit(
        image,
        (target_width, target_height),
        method=Image.Resampling.LANCZOS,
    )