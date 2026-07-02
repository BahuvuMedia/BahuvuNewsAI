"""
BAHUVU News - Branding Configuration
"""

# -------------------------------------------------
# BRAND
# -------------------------------------------------

BRAND = {
    "name": "Bahuvu News",
    "english": "BAHUVU NEWS",
    "telugu": "బహువు న్యూస్",
    "tagline": "Fast • Trusted • Accurate",
}

# -------------------------------------------------
# COLORS
# -------------------------------------------------

COLORS = {
    "primary": "#D50000",
    "secondary": "#FFC107",
    "white": "#FFFFFF",
    "black": "#1A1A1A",
}

# -------------------------------------------------
# VIDEO
# -------------------------------------------------

VIDEO = {
    "fps": 24,
}

# -------------------------------------------------
# WATERMARK
# -------------------------------------------------

WATERMARK = {
    "enabled": True,
    "opacity": 0.20,
    "interval": 8,
    "margin_x": 30,
    "margin_y": 30,
}

# -------------------------------------------------
# LAYOUT
# -------------------------------------------------

LAYOUT = {
    "lower_third_height": 120,
    "category_bar_height": 70,
}

# -------------------------------------------------
# INTRO / OUTRO
# -------------------------------------------------

INTRO_DURATION = 4
OUTRO_DURATION = 4


def get_brand_name():
    return BRAND["name"]


def get_logo_text():
    return BRAND["english"]


def get_telugu_name():
    return BRAND["telugu"]


def get_brand_color(name="primary"):
    return COLORS.get(name, COLORS["primary"])


if __name__ == "__main__":
    print("Brand :", get_brand_name())
    print("Logo  :", get_logo_text())
    print("Color :", get_brand_color())