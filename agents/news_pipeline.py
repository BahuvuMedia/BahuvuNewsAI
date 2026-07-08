# agents/news_pipeline.py

"""
BahuvuNewsAI - Safe News Pipeline Bridge
Version: v1.2

Purpose:
- Use existing news_fetcher.py without rewriting it
- Convert fetched news into final_graphic_generator format
- Generate one final publishable news graphic safely
"""

from agents.news_fetcher import fetch_latest_news
from agents.final_graphic_generator import generate_final_news_graphic


DEFAULT_LOCAL_IMAGE = "assets/images/sample.jpg"


def normalize_news(news):
    if not news:
        return None

    return {
        "title": news.get("title", "BREAKING NEWS"),
        "summary": (
            news.get("summary")
            or news.get("description")
            or news.get("content")
            or "More details are expected soon."
        ),
        "category": news.get("category", "GENERAL"),
        "image_path": DEFAULT_LOCAL_IMAGE,
        "source": news.get("source", "Google News"),
        "link": news.get("link", ""),
    }


def run_news_pipeline():
    print("=" * 50)
    print("BahuvuNewsAI News Pipeline v1.2")
    print("=" * 50)

    raw_news = fetch_latest_news()

    if not raw_news:
        print("No news available for graphic generation.")
        return None

    prepared_news = normalize_news(raw_news)

    print("Generating final graphic from fetched news...")
    output_path = generate_final_news_graphic(prepared_news)

    print("Pipeline completed successfully.")
    print(f"Output: {output_path}")

    return output_path


if __name__ == "__main__":
    run_news_pipeline()