# agents/news_filter.py

"""
BahuvuNewsAI - News Filter
Version: v1.6

Filters cleaned news articles before ranking and editorial selection.

This module decides whether an article should be kept or rejected.
It does not fetch, clean, rank, translate, or generate content.
"""

from agents.config import BAD_KEYWORDS


MIN_TITLE_LENGTH = 20
MIN_DESCRIPTION_LENGTH = 30


def normalize_text(text):
    """Normalize text for comparison."""
    if not text:
        return ""
    return str(text).strip().lower()


def contains_bad_keyword(article):
    """Check whether article contains unwanted keywords."""
    title = normalize_text(article.get("title", ""))
    description = normalize_text(article.get("description", ""))

    combined_text = f"{title} {description}"

    for keyword in BAD_KEYWORDS:
        if keyword.lower() in combined_text:
            return True

    return False


def has_required_fields(article):
    """Ensure article has minimum required fields."""
    if not article:
        return False

    title = str(article.get("title", "")).strip()
    description = str(article.get("description", "")).strip()

    if len(title) < MIN_TITLE_LENGTH:
        return False

    if len(description) < MIN_DESCRIPTION_LENGTH:
        return False

    return True


def is_duplicate(article, seen_titles):
    """Detect duplicate stories using normalized title."""
    title = normalize_text(article.get("title", ""))

    if not title:
        return True

    if title in seen_titles:
        return True

    seen_titles.add(title)
    return False


def should_keep_article(article, seen_titles=None):
    """Return True if article passes editorial filtering."""
    if seen_titles is None:
        seen_titles = set()

    if not has_required_fields(article):
        return False

    if contains_bad_keyword(article):
        return False

    if is_duplicate(article, seen_titles):
        return False

    return True


def filter_articles(articles):
    """Filter a list of article dictionaries."""
    if not articles:
        return []

    filtered_articles = []
    seen_titles = set()

    for article in articles:
        if should_keep_article(article, seen_titles):
            filtered_articles.append(article)

    return filtered_articles


if __name__ == "__main__":
    sample_articles = [
        {
            "title": "Heavy Rain Alert Issued Across Andhra Pradesh Districts",
            "description": "Officials advise people to stay alert as rainfall continues in several districts.",
            "source": "Test Source",
        },
        {
            "title": "Stock Market Update Today",
            "description": "Share prices moved higher during morning trade.",
            "source": "Test Source",
        },
        {
            "title": "Short",
            "description": "Too short.",
            "source": "Test Source",
        },
    ]

    filtered = filter_articles(sample_articles)

    print("Filtered articles:", len(filtered))

    for article in filtered:
        print("-", article["title"])