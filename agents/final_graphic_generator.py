# agents/final_graphic_generator.py

from pathlib import Path
from datetime import datetime

from agents.news_template import create_news_template
from agents.headline_formatter import format_headline


OUTPUT_DIR = Path("outputs") / "graphics"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_IMAGE = "assets/images/sample.jpg"


def clean_text(value, fallback=""):
    if value is None:
        return fallback

    value = str(value).strip()
    return value if value else fallback


def prepare_news_data(news):
    title = clean_text(news.get("title"), "BREAKING NEWS")

    return {
        "title": format_headline(title),
        "summary": clean_text(
            news.get("summary"),
            "More details are expected soon."
        ),
        "category": clean_text(news.get("category"), "GENERAL").upper(),
        "image_path": clean_text(news.get("image_path"), DEFAULT_IMAGE),
        "date": clean_text(
            news.get("date"),
            datetime.now().strftime("%d %B %Y")
        ),
        "source": clean_text(news.get("source"), "BAHUVU NEWS"),
    }


def generate_final_news_graphic(news, filename="final_news_graphic.png"):
    prepared_news = prepare_news_data(news)

    template_path = create_news_template(prepared_news)

    output_path = OUTPUT_DIR / filename
    source_path = Path(template_path)

    if source_path != output_path:
        output_path.write_bytes(source_path.read_bytes())

    print("=" * 50)
    print("BahuvuNewsAI Final Graphic Generator")
    print("=" * 50)
    print(f"Title    : {prepared_news['title']}")
    print(f"Category : {prepared_news['category']}")
    print(f"Image    : {prepared_news['image_path']}")
    print(f"Created  : {output_path}")

    return output_path


if __name__ == "__main__":
    sample_news = {
        "title": "Heavy Rain Continues Across Andhra Pradesh As Officials Issue Alert",
        "summary": "Officials have advised people to stay alert as heavy rainfall continues in several districts. Emergency teams are monitoring low-lying areas.",
        "category": "WEATHER",
        "image_path": DEFAULT_IMAGE,
        "source": "BAHUVU NEWS",
    }

    generate_final_news_graphic(sample_news)