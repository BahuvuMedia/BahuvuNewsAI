# agents/layout.py

from agents.theme import LAYOUT

WIDTH = LAYOUT["width"]
HEIGHT = LAYOUT["height"]
MARGIN = LAYOUT["margin"]

HEADER = {
    "x1": 0,
    "y1": 0,
    "x2": WIDTH,
    "y2": LAYOUT["header_height"],
}

FOOTER = {
    "x1": 0,
    "y1": HEIGHT - LAYOUT["footer_height"],
    "x2": WIDTH,
    "y2": HEIGHT,
}

MEDIA_PANEL = {
    "x1": 70,
    "y1": 160,
    "x2": 1180,
    "y2": 830,
}

HEADLINE_PANEL = {
    "x1": 1230,
    "y1": 160,
    "x2": 1850,
    "y2": 830,
}

LOGO_BOX = {
    "x1": 1580,
    "y1": 20,
    "x2": 1870,
    "y2": 90,
}