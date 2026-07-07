# agents/photo_layout.py

from pathlib import Path
from PIL import Image, ImageDraw

try:
    from agents.layout import WIDTH, HEIGHT
except Exception:
    WIDTH, HEIGHT = 1920, 1080


def resize_and_crop(image, target_size):
    target_w, target_h = target_size
    img_w, img_h = image.size

    scale = max(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)

    image = image.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2

    return image.crop((left, top, left + target_w, top + target_h))


def load_photo(image_path):
    if not image_path:
        return None

    path = Path(image_path)

    if not path.exists():
        return None

    try:
        return Image.open(path).convert("RGB")
    except Exception:
        return None


def create_background_photo(image_path):
    photo = load_photo(image_path)

    if photo is None:
        return Image.new("RGB", (WIDTH, HEIGHT), (18, 18, 22))

    return resize_and_crop(photo, (WIDTH, HEIGHT))


def add_photo_frame(image):
    draw = ImageDraw.Draw(image)

    margin = 34
    draw.rectangle(
        (margin, margin, WIDTH - margin, HEIGHT - margin),
        outline=(255, 255, 255),
        width=2,
    )

    return image