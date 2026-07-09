# agents/news_cleaner.py

"""
BahuvuNewsAI - News Cleaner
Version: v1.5

Cleans and normalizes fetched news articles.
This module does not fetch, filter, rank, translate, or make editorial decisions.
"""

import html
import re
from bs4 import BeautifulSoup


def clean_html(text):
    """Remove HTML tags and decode HTML entities."""
    if not text:
        return ""

    text = html.unescape(str(text))
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(" ", strip=True)


def normalize_whitespace(text):
    """Normalize spaces, tabs, and newlines."""
    if not text:
        return ""

    text = str(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_text(text):
    """Clean a normal text field without changing meaning."""
    if not text:
        return ""

    text = clean_html(text)
    text = normalize_whitespace(text)

    return text


def clean_article(article):
    """Return a cleaned copy of one article dictionary."""
    if not article:
        return {}

    cleaned = dict(article)

    cleaned["title"] = clean_text(cleaned.get("title", ""))
    cleaned["description"] = clean_text(cleaned.get("description", ""))
    cleaned["summary"] = clean_text(cleaned.get("summary", cleaned.get("description", "")))
    cleaned["content"] = clean_text(cleaned.get("content", cleaned.get("description", "")))

    if not cleaned["summary"]:
        cleaned["summary"] = cleaned["description"]

    if not cleaned["content"]:
        cleaned["content"] = cleaned["description"]

    return cleaned


def clean_articles(articles):
    """Clean a list of article dictionaries."""
    if not articles:
        return []

    cleaned_articles = []

    for article in articles:
        cleaned_article_item = clean_article(article)

        if cleaned_article_item.get("title"):
            cleaned_articles.append(cleaned_article_item)

    return cleaned_articles


if __name__ == "__main__":
    sample_article = {
        "title": "  Heavy Rain &amp; Alert Issued  ",
        "description": "<p>Officials&nbsp;advise people to stay alert.</p>",
        "content": "<div>Heavy rainfall continues across several districts.</div>",
        "summary": "",
        "image": None,
        "link": "https://example.com",
        "score": 10,
        "source": "Test Source",
    }

    cleaned = clean_article(sample_article)

    print("TITLE:", cleaned["title"])
    print("DESCRIPTION:", cleaned["description"])
    print("SUMMARY:", cleaned["summary"])
    print("CONTENT:", cleaned["content"])