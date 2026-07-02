# agents/themes.py

THEMES = {
    "BREAKING": {
        "label": "🚨 BREAKING NEWS",
        "primary": "#B00020",
        "secondary": "#7F0017",
        "accent": "#FFFFFF",
        "icon": "🚨",
    },
    "WEATHER": {
        "label": "🌦️ WEATHER | వాతావరణం",
        "primary": "#16A34A",
        "secondary": "#064E3B",
        "accent": "#BBF7D0",
        "icon": "🌦️",
    },
    "POLITICS": {
        "label": "🏛️ POLITICS | రాజకీయాలు",
        "primary": "#EA580C",
        "secondary": "#7C2D12",
        "accent": "#FED7AA",
        "icon": "🏛️",
    },
    "BUSINESS": {
        "label": "💹 BUSINESS | వ్యాపారం",
        "primary": "#FACC15",
        "secondary": "#713F12",
        "accent": "#FEF08A",
        "icon": "💹",
    },
    "SPORTS": {
        "label": "⚽ SPORTS | క్రీడలు",
        "primary": "#7C3AED",
        "secondary": "#4C1D95",
        "accent": "#DDD6FE",
        "icon": "⚽",
    },
    "ENTERTAINMENT": {
        "label": "🎬 ENTERTAINMENT | వినోదం",
        "primary": "#DB2777",
        "secondary": "#831843",
        "accent": "#FBCFE8",
        "icon": "🎬",
    },
    "TECHNOLOGY": {
        "label": "💻 TECHNOLOGY | సాంకేతికం",
        "primary": "#2563EB",
        "secondary": "#1E3A8A",
        "accent": "#BFDBFE",
        "icon": "💻",
    },
    "HEALTH": {
        "label": "❤️ HEALTH | ఆరోగ్యం",
        "primary": "#DC2626",
        "secondary": "#7F1D1D",
        "accent": "#FECACA",
        "icon": "❤️",
    },
    "WORLD": {
        "label": "🌍 WORLD | ప్రపంచం",
        "primary": "#0891B2",
        "secondary": "#164E63",
        "accent": "#CFFAFE",
        "icon": "🌍",
    },
    "EDUCATION": {
        "label": "🎓 EDUCATION | విద్య",
        "primary": "#4F46E5",
        "secondary": "#312E81",
        "accent": "#C7D2FE",
        "icon": "🎓",
    },
    "GENERAL": {
        "label": "📰 NEWS | వార్తలు",
        "primary": "#38BDF8",
        "secondary": "#0F172A",
        "accent": "#E0F2FE",
        "icon": "📰",
    },
}


def get_theme(category="GENERAL"):
    category = category.upper().strip()
    return THEMES.get(category, THEMES["GENERAL"])


def get_theme_label(category="GENERAL"):
    return get_theme(category)["label"]


def get_theme_color(category="GENERAL"):
    return get_theme(category)["primary"]