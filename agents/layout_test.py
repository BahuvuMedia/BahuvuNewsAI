# agents/layout_test.py

from PIL import Image, ImageDraw

from agents.layout import (
    WIDTH,
    HEIGHT,
    HEADER,
    FOOTER,
    MEDIA_PANEL,
    HEADLINE_PANEL,
    LOGO_BOX,
)

img = Image.new("RGB", (WIDTH, HEIGHT), "#222222")
draw = ImageDraw.Draw(img)

boxes = {
    "HEADER": HEADER,
    "FOOTER": FOOTER,
    "MEDIA_PANEL": MEDIA_PANEL,
    "HEADLINE_PANEL": HEADLINE_PANEL,
    "LOGO_BOX": LOGO_BOX,
}

for name, box in boxes.items():
    rect = (box["x1"], box["y1"], box["x2"], box["y2"])
    draw.rectangle(rect, outline="white", width=5)
    draw.text((box["x1"] + 10, box["y1"] + 10), name, fill="white")

img.save("outputs/graphics/layout_test.png")
print("Layout test created: outputs/graphics/layout_test.png")