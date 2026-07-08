# agents/layout.py

"""
BahuvuNewsAI - Master Broadcast Layout Engine
Version: v0.95

This file is the single source of truth for all screen dimensions,
regions, spacing, and positioning used by the graphics system.
"""

from dataclasses import dataclass


# ==========================================================
# CANVAS
# ==========================================================

WIDTH = 1280
HEIGHT = 720

CANVAS = {
    "width": WIDTH,
    "height": HEIGHT,
}


# ==========================================================
# BASIC SPACING SYSTEM
# ==========================================================

MARGIN = 40
GAP = 24
SMALL_GAP = 12
LARGE_GAP = 36

PADDING_SMALL = 12
PADDING_MEDIUM = 20
PADDING_LARGE = 32

CORNER_RADIUS = 18


# ==========================================================
# REGION MODEL
# ==========================================================

@dataclass(frozen=True)
class Region:
    x: int
    y: int
    width: int
    height: int

    @property
    def left(self):
        return self.x

    @property
    def top(self):
        return self.y

    @property
    def right(self):
        return self.x + self.width

    @property
    def bottom(self):
        return self.y + self.height

    @property
    def box(self):
        return (self.x, self.y, self.right, self.bottom)


# ==========================================================
# MAIN BROADCAST REGIONS
# ==========================================================

HEADER = Region(
    x=0,
    y=0,
    width=WIDTH,
    height=90,
)

CATEGORY = Region(
    x=MARGIN,
    y=105,
    width=360,
    height=46,
)

PHOTO = Region(
    x=MARGIN,
    y=165,
    width=430,
    height=355,
)

TEXT = Region(
    x=500,
    y=165,
    width=740,
    height=355,
)

HEADLINE = Region(
    x=TEXT.x,
    y=TEXT.y,
    width=TEXT.width,
    height=175,
)

SUMMARY = Region(
    x=TEXT.x,
    y=HEADLINE.bottom + 20,
    width=TEXT.width,
    height=160,
)

FOOTER = Region(
    x=0,
    y=640,
    width=WIDTH,
    height=80,
)

SAFE_AREA = Region(
    x=MARGIN,
    y=HEADER.bottom,
    width=WIDTH - (MARGIN * 2),
    height=FOOTER.y - HEADER.bottom,
)


# ==========================================================
# COMPATIBILITY CONSTANTS
# Existing modules can still import these names safely.
# ==========================================================

HEADER_HEIGHT = HEADER.height
FOOTER_HEIGHT = FOOTER.height

PHOTO_X = PHOTO.x
PHOTO_Y = PHOTO.y
PHOTO_WIDTH = PHOTO.width
PHOTO_HEIGHT = PHOTO.height

TEXT_X = TEXT.x
TEXT_Y = TEXT.y
TEXT_WIDTH = TEXT.width
TEXT_HEIGHT = TEXT.height

HEADLINE_X = HEADLINE.x
HEADLINE_Y = HEADLINE.y
HEADLINE_WIDTH = HEADLINE.width
HEADLINE_HEIGHT = HEADLINE.height

SUMMARY_X = SUMMARY.x
SUMMARY_Y = SUMMARY.y
SUMMARY_WIDTH = SUMMARY.width
SUMMARY_HEIGHT = SUMMARY.height

CATEGORY_X = CATEGORY.x
CATEGORY_Y = CATEGORY.y
CATEGORY_WIDTH = CATEGORY.width
CATEGORY_HEIGHT = CATEGORY.height

FOOTER_Y = FOOTER.y


# ==========================================================
# HELPERS
# ==========================================================

def get_region(name: str) -> Region:
    regions = {
        "header": HEADER,
        "category": CATEGORY,
        "photo": PHOTO,
        "text": TEXT,
        "headline": HEADLINE,
        "summary": SUMMARY,
        "footer": FOOTER,
        "safe_area": SAFE_AREA,
    }

    key = name.lower().strip()

    if key not in regions:
        raise ValueError(f"Unknown layout region: {name}")

    return regions[key]


def scale_value(value: int, target_width: int = WIDTH) -> int:
    """
    Scale a value from the base 1280px layout to another width.
    Useful later for 1920x1080, vertical video, or social formats.
    """
    return int(value * (target_width / WIDTH))


def center_x(region_width: int, canvas_width: int = WIDTH) -> int:
    return (canvas_width - region_width) // 2


def center_y(region_height: int, canvas_height: int = HEIGHT) -> int:
    return (canvas_height - region_height) // 2