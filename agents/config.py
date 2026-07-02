# agents/config.py

from pathlib import Path

# Project
PROJECT_NAME = "Bahuvu News AI"
CHANNEL_NAME = "BAHUVU NEWS"

# Base directories
BASE_DIR = Path(".")
ASSETS_DIR = BASE_DIR / "assets"
OUTPUT_DIR = BASE_DIR / "outputs"
DATA_DIR = BASE_DIR / "data"

# Assets
FONTS_DIR = ASSETS_DIR / "fonts"
LOGOS_DIR = ASSETS_DIR / "logos"
ICONS_DIR = ASSETS_DIR / "icons"
BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"
MUSIC_DIR = ASSETS_DIR / "music"
OVERLAYS_DIR = ASSETS_DIR / "overlays"
TEMPLATES_DIR = ASSETS_DIR / "templates"
SOUNDS_DIR = ASSETS_DIR / "sounds"

# Outputs
GRAPHICS_DIR = OUTPUT_DIR / "graphics"
THUMBNAILS_DIR = OUTPUT_DIR / "thumbnails"
SHORTS_DIR = OUTPUT_DIR / "shorts"
VIDEOS_DIR = OUTPUT_DIR / "videos"
AUDIO_DIR = OUTPUT_DIR / "audio"
TEMP_DIR = OUTPUT_DIR / "temp"