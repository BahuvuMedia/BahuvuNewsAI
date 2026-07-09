# agents/news_fetcher.py

"""
BahuvuNewsAI - News Fetcher
Version: v1.4

Fetches, cleans, filters, and scores RSS news articles.
This module does NOT make final editorial decisions.
It prepares clean news data for the pipeline.
"""

import feedparser
from bs4 import BeautifulSoup

from agents.config import RSS_URL, BAD_KEYWORDS, PREFERRED_KEYWORDS


def clean_html(text):
    """Remove HTML tags from RSS descriptions."""
    if not text:
        return ""

    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(" ", strip=True)


def normalize_text(text):
    """Normalize text for safer comparison."""
    if not text:
        return ""
    return str(text).strip()


def is_valid_news(title):
    """Reject advertisements, market reports, and unwanted items."""
    title = normalize_text(title).lower()

    if not title:
        return False

    return not any(keyword.lower() in title for keyword in BAD_KEYWORDS)


def calculate_score(title, description=""):
    """Score news based on preferred keywords."""
    text = f"{title} {description}".lower()

    score = 0

    for keyword in PREFERRED_KEYWORDS:
        if keyword.lower() in text:
            score += 10

    return score


def extract_image(entry):
    """Extract image URL from RSS entry if available."""
    if "media_content" in entry and entry.media_content:
        return entry.media_content[0].get("url")

    if "media_thumbnail" in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")

    return None


def build_article(entry):
    """Convert RSS entry into a clean article dictionary."""
    title = normalize_text(entry.get("title", ""))
    description = clean_html(entry.get("summary", ""))
    link = entry.get("link")
    image = extract_image(entry)

    return {
        "title": title,
        "description": description,
        "content": description,
        "summary": description,
        "image": image,
        "link": link,
        "score": calculate_score(title, description),
        "source": "Google News RSS",
    }


def fetch_news(limit=10):
    """Fetch multiple clean news articles from RSS."""
    print("Fetching news from RSS...")

    feed = feedparser.parse(RSS_URL)

    if not feed.entries:
        print("No news found.")
        return []

    articles = []

    for entry in feed.entries:
        title = normalize_text(entry.get("title", ""))

        if not is_valid_news(title):
            continue

        article = build_article(entry)
        articles.append(article)

    articles.sort(key=lambda item: item["score"], reverse=True)

    selected_articles = articles[:limit]

    print(f"Fetched {len(selected_articles)} usable news articles.")

    return selected_articles


def fetch_latest_news():
    """
    Backward-compatible helper.

    Returns the highest-scoring article, or None.
    Existing pipeline code can continue using this safely.
    """
    articles = fetch_news(limit=10)

    if not articles:
        print("No suitable news article found.")
        return None

    best_article = articles[0]

    print("News selected:")
    print(best_article["title"])

    return best_article


if __name__ == "__main__":
    latest = fetch_latest_news()

    if latest:
        print("-" * 60)
        print("TITLE:", latest["title"])
        print("SCORE:", latest["score"])
        print("LINK:", latest["link"])