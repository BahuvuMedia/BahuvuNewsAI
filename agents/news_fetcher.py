# agents/news_fetcher.py

"""
BahuvuNewsAI - News Fetcher
Version: v1.8

Fetches raw RSS news articles.

This module only collects articles from RSS sources and converts them into
a consistent article dictionary.

Filtering, cleaning, and ranking are handled by separate modules.
"""

import feedparser

from agents.config import RSS_URL
from agents.news_cleaner import clean_articles
from agents.news_filter import filter_articles
from agents.news_ranker import rank_articles, get_top_article


def normalize_text(text):
    """Normalize basic text values safely."""
    if not text:
        return ""
    return str(text).strip()


def extract_image(entry):
    """Extract image URL from RSS entry if available."""
    if "media_content" in entry and entry.media_content:
        return entry.media_content[0].get("url")

    if "media_thumbnail" in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")

    return None


def build_article(entry):
    """Convert RSS entry into a standard raw article dictionary."""
    title = normalize_text(entry.get("title", ""))
    description = normalize_text(entry.get("summary", ""))
    link = entry.get("link")
    image = extract_image(entry)

    return {
        "title": title,
        "description": description,
        "summary": description,
        "content": description,
        "image": image,
        "link": link,
        "source": "Google News RSS",
    }


def fetch_news(limit=20):
    """Fetch raw news articles from RSS."""
    print("Fetching raw news from RSS...")

    feed = feedparser.parse(RSS_URL)

    if not feed.entries:
        print("No news found.")
        return []

    articles = []

    for entry in feed.entries:
        article = build_article(entry)

        if article.get("title"):
            articles.append(article)

    selected_articles = articles[:limit]

    print(f"Fetched {len(selected_articles)} raw news articles.")

    return selected_articles


def fetch_latest_news():
    """
    Backward-compatible helper.

    Fetches, cleans, filters, ranks, and returns the best article.
    This keeps older pipeline code working safely.
    """
    raw_articles = fetch_news(limit=20)
    cleaned_articles = clean_articles(raw_articles)
    filtered_articles = filter_articles(cleaned_articles)
    ranked_articles = rank_articles(filtered_articles)

    best_article = get_top_article(ranked_articles)

    if not best_article:
        print("No suitable news article found.")
        return None

    print("News selected:")
    print(best_article["title"])
    print("Rank score:", best_article.get("rank_score", 0))

    return best_article


if __name__ == "__main__":
    latest = fetch_latest_news()

    if latest:
        print("-" * 60)
        print("TITLE:", latest["title"])
        print("RANK SCORE:", latest.get("rank_score", 0))
        print("LINK:", latest.get("link"))