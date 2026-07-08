# agents/broadcast_layout.py

"""
BahuvuNewsAI - Broadcast Layout Manager
Version: v0.95

This module exposes clean layout helpers while using agents.layout
as the single source of truth for all dimensions and positions.
"""

from agents.layout import (
    WIDTH,
    HEIGHT,
    MARGIN,
    GAP,
    SMALL_GAP,
    LARGE_GAP,
    PADDING_SMALL,
    PADDING_MEDIUM,
    PADDING_LARGE,
    CORNER_RADIUS,
    HEADER,
    CATEGORY,
    PHOTO,
    TEXT,
    HEADLINE,
    SUMMARY,
    FOOTER,
    SAFE_AREA,
    get_region,
)


BROADCAST_LAYOUT = {
    "canvas": {
        "width": WIDTH,
        "height": HEIGHT,
    },
    "spacing": {
        "margin": MARGIN,
        "gap": GAP,
        "small_gap": SMALL_GAP,
        "large_gap": LARGE_GAP,
        "padding_small": PADDING_SMALL,
        "padding_medium": PADDING_MEDIUM,
        "padding_large": PADDING_LARGE,
        "corner_radius": CORNER_RADIUS,
    },
    "regions": {
        "header": HEADER,
        "category": CATEGORY,
        "photo": PHOTO,
        "text": TEXT,
        "headline": HEADLINE,
        "summary": SUMMARY,
        "footer": FOOTER,
        "safe_area": SAFE_AREA,
    },
}


def get_canvas_size():
    return WIDTH, HEIGHT


def get_layout():
    return BROADCAST_LAYOUT


def get_layout_region(name: str):
    return get_region(name)


def get_region_box(name: str):
    return get_region(name).box


def get_region_position(name: str):
    region = get_region(name)
    return region.x, region.y


def get_region_size(name: str):
    region = get_region(name)
    return region.width, region.height


def get_text_start_position():
    return TEXT.x, TEXT.y


def get_photo_box():
    return PHOTO.box


def get_headline_box():
    return HEADLINE.box


def get_summary_box():
    return SUMMARY.box


def get_footer_box():
    return FOOTER.box


def get_header_box():
    return HEADER.box


def get_category_box():
    return CATEGORY.box