"""
BAHUVU News - Branding Configuration
"""

BRAND = {
    "name": "Bahuvu News",
    "english": "BAHUVU NEWS",
    "telugu": "Bahuvu News",
    "tagline": "Fast • Trusted •Accurate",
}

COLORS = {
    "primary": "#D50000",
    "secondary": "#FFC107",
    "white": "#FFFFFF",
    "black": "#1A1A1A",
}

def get_brand_name():
    return BRAND["name"]

def get_logo_text():
    return BRAND["english"]

def get_brand_color(name="primary"):
    return COLORS.get(name, COLORS["primary"])

if __name__ == "__main__":
    print("Brand :", get_brand_name())
    print("Logo  :", get_logo_text())
    print("Color :", get_brand_color())