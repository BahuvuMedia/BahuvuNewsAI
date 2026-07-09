# agents/article_model.py

"""
BahuvuNewsAI - Unified Article Model
Version: v2.0

This module defines the standard article structure used
throughout BahuvuNewsAI.

Every processing stage should accept and return this model.
"""

from copy import deepcopy


ARTICLE_TEMPLATE = {
    # Identity
    "id": "",

    # Editorial
    "title": "",
    "summary": "",
    "content": "",
    "category": "GENERAL",

    # Source
    "source": "",
    "article_url": "",
    "published_at": "",

    # Media
    "image_url": "",

    # Processing
    "rank_score": 0,
    "language": "en",

    # Metadata
    "tags": [],
    "metadata": {},
}


def create_article(**kwargs):
    """
    Create a new standardized article dictionary.

    Unknown fields are accepted to support future expansion.
    """
    article = deepcopy(ARTICLE_TEMPLATE)

    for key, value in kwargs.items():
        article[key] = value

    return article


def normalize_article(article):
    """
    Convert any article dictionary into the standard format.

    Supports backward compatibility with older pipeline fields.
    """
    if not article:
        return create_article()

    normalized = create_article()

    normalized["id"] = article.get("id", "")

    normalized["title"] = article.get("title", "")

    normalized["summary"] = (
        article.get("summary")
        or article.get("description")
        or ""
    )

    normalized["content"] = (
        article.get("content")
        or normalized["summary"]
    )

    normalized["category"] = (
        article.get("category")
        or "GENERAL"
    )

    normalized["source"] = article.get("source", "")

    normalized["article_url"] = (
        article.get("article_url")
        or article.get("link")
        or ""
    )

    normalized["published_at"] = article.get(
        "published_at",
        ""
    )

    normalized["image_url"] = (
        article.get("image_url")
        or article.get("image")
        or article.get("image_path")
        or ""
    )

    normalized["rank_score"] = (
        article.get("rank_score")
        or article.get("score")
        or 0
    )

    normalized["language"] = article.get(
        "language",
        "en"
    )

    normalized["tags"] = list(article.get("tags", []))

    normalized["metadata"] = dict(
        article.get("metadata", {})
    )

    return normalized


def normalize_articles(articles):
    """
    Normalize a list of articles.
    """
    if not articles:
        return []

    return [
        normalize_article(article)
        for article in articles
    ]


if __name__ == "__main__":

    sample = {
        "title": "Heavy Rain Alert",
        "description": "Officials issue alert.",
        "image": "sample.jpg",
        "link": "https://example.com",
        "score": 75,
    }

    article = normalize_article(sample)

    print("=" * 50)

    for key, value in article.items():
        print(f"{key:15}: {value}")