import os

from dotenv import load_dotenv

load_dotenv()

"""
==========================================
BAHUVU NEWS AI
Configuration File
==========================================
"""

# ==========================================
# PROJECT PATHS
# ==========================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ASSETS_DIR = os.path.join(BASE_DIR, "assets")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")

os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# ==========================================
# API KEYS
# ==========================================

# Replace with your own Gemini API key

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ==========================================
# NEWS SOURCE
# ==========================================

RSS_URL = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"

# ==========================================
# DEFAULT IMAGE
# ==========================================

# Used when RSS doesn't provide an image
DEFAULT_IMAGE = "https://picsum.photos/1280/720"

# ==========================================
# VOICE SETTINGS
# ==========================================

TELUGU_VOICE = "te-IN-ShrutiNeural"

# ==========================================
# OUTPUT FILES
# ==========================================

NEWS_IMAGE = os.path.join(ASSETS_DIR, "news.jpg")
OUTPUT_AUDIO = os.path.join(OUTPUTS_DIR, "output.mp3")
OUTPUT_VIDEO = os.path.join(OUTPUTS_DIR, "news_video.mp4")
OUTPUT_SCRIPT = os.path.join(OUTPUTS_DIR, "script.txt")

# ==========================================
# FILTER WORDS
# ==========================================

BAD_KEYWORDS = [
    "market",
    "forecast",
    "research",
    "report",
    "share",
    "stock",
    "analysis",
    "globenewswire",
    "pr newswire",
    "business wire",
    "earnings",
    "dividend",
    "ipo",
    "financial results"
]

PREFERRED_KEYWORDS = [
    "india",
    "andhra",
    "telangana",
    "isro",
    "space",
    "science",
    "technology",
    "ai",
    "health",
    "education",
    "parliament",
    "prime minister",
    "president",
    "supreme court",
    "election",
    "sports",
    "cricket",
    "olympics",
    "economy"

]