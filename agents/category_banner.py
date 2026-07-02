"""
Bahuvu News Category Banner Module
Detects news category and prepares banner information.
"""

from agents.branding import (
    PRIMARY_RED,
    SECONDARY_GOLD,
    WHITE,
    BLACK,
)


CATEGORIES = [
    {
        "key": "weather",
        "english": "WEATHER",
        "telugu": "వాతావరణం",
        "icon": "🌦️",
        "color": "#F57C00",
        "keywords": [
            "rain", "monsoon", "weather", "imd", "cyclone", "storm",
            "flood", "heatwave", "temperature", "వర్షం", "రుతుపవనాలు"
        ],
    },
    {
        "key": "isro",
        "english": "ISRO",
        "telugu": "ఇస్రో",
        "icon": "🛰️",
        "color": "#1565C0",
        "keywords": [
            "isro", "space", "satellite", "rocket", "nasa",
            "astronaut", "space station", "moon", "mars"
        ],
    },
    {
        "key": "technology",
        "english": "TECHNOLOGY",
        "telugu": "టెక్నాలజీ",
        "icon": "💻",
        "color": "#0D47A1",
        "keywords": [
            "technology", "tech", "ai", "artificial intelligence",
            "software", "google", "microsoft", "apple", "openai"
        ],
    },
    {
        "key": "politics",
        "english": "POLITICS",
        "telugu": "రాజకీయాలు",
        "icon": "🏛️",
        "color": PRIMARY_RED,
        "keywords": [
            "government", "minister", "parliament", "election",
            "president", "prime minister", "cm", "mla", "mp",
            "bjp", "congress"
        ],
    },
    {
        "key": "sports",
        "english": "SPORTS",
        "telugu": "క్రీడలు",
        "icon": "⚽",
        "color": "#2E7D32",
        "keywords": [
            "cricket", "football", "sports", "match", "ipl",
            "world cup", "olympics", "tennis", "hockey"
        ],
    },
    {
        "key": "business",
        "english": "BUSINESS",
        "telugu": "వ్యాపారం",
        "icon": "💹",
        "color": "#212121",
        "keywords": [
            "business", "economy", "market", "stock", "rupee",
            "rbi", "inflation", "gdp", "trade"
        ],
    },
    {
        "key": "health",
        "english": "HEALTH",
        "telugu": "ఆరోగ్యం",
        "icon": "🏥",
        "color": "#00897B",
        "keywords": [
            "health", "hospital", "doctor", "virus", "covid",
            "medicine", "disease", "vaccine"
        ],
    },
    {
        "key": "world",
        "english": "WORLD",
        "telugu": "ప్రపంచం",
        "icon": "🌍",
        "color": "#6A1B9A",
        "keywords": [
            "world", "us", "usa", "china", "russia", "iran",
            "israel", "ukraine", "europe", "united nations"
        ],
    },
]


DEFAULT_CATEGORY = {
    "key": "breaking",
    "english": "BREAKING NEWS",
    "telugu": "తాజా వార్త",
    "icon": "🔴",
    "color": PRIMARY_RED,
}


def detect_category(text):
    """
    Detect category from news title/content.
    """

    if not text:
        return DEFAULT_CATEGORY

    text_lower = text.lower()

    for category in CATEGORIES:
        for keyword in category["keywords"]:
            if keyword.lower() in text_lower:
                return category

    return DEFAULT_CATEGORY


def get_category_label(category):
    """
    Return display label for category banner.
    """

    return f'{category["icon"]} {category["english"]} | {category["telugu"]}'