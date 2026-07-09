# agents/article_cleaner.py

"""
BahuvuNewsAI - Article Cleaner
Version: v1.5

Cleans raw news articles before translation, summarization,
graphics, voice generation, and video production.
"""

import re
from copy import deepcopy


JUNK_PATTERNS = [
    r"read more.*",
    r"click here.*",
    r"subscribe.*",
    r"follow us.*",
    r"advertisement",
    r"also read.*",
    r"watch video.*",
    r"download app.*",
    r"copyright.*",
    r"all rights reserved.*",
]


LOW_QUALITY_SOURCES = [
    "unknown",
    "anonymous",
    "test",
    "sample",
]


def clean_whitespace(text):
    if not text:
        return ""

    text = str(text)
    text = text.replace("\n", " ")
    text = text.replace("\t", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def remove_junk_phrases(text):
    if not text:
        return ""

    cleaned = text

    for pattern in JUNK_PATTERNS:
        cleaned = re.sub(
            pattern,
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

    return clean_whitespace(cleaned)


def remove_duplicate_sentences(text):
    if not text:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", text)
    seen = set()
    final_sentences = []

    for sentence in sentences:
        normalized = sentence.lower().strip()

        if not normalized:
            continue

        if normalized in seen:
            continue

        seen.add(normalized)
        final_sentences.append(sentence.strip())

    return " ".join(final_sentences).strip()


def clean_text(text):
    text = clean_whitespace(text)
    text = remove_junk_phrases(text)
    text = remove_duplicate_sentences(text)
    return clean_whitespace(text)


def score_source_quality(source):
    if not source:
        return 40

    source = str(source).lower().strip()

    for bad_source in LOW_QUALITY_SOURCES:
        if bad_source in source:
            return 30

    if len(source) < 3:
        return 40

    return 80


def score_text_quality(title, summary, content):
    score = 100

    title = clean_whitespace(title)
    summary = clean_whitespace(summary)
    content = clean_whitespace(content)

    if len(title) < 20:
        score -= 20

    if len(summary) < 40:
        score -= 20

    if len(content) < 80:
        score -= 25

    combined = f"{title} {summary} {content}".lower()

    for pattern in JUNK_PATTERNS:
        if re.search(pattern, combined, flags=re.IGNORECASE):
            score -= 10

    return max(0, min(100, score))


def clean_article(article):
    """
    Takes a raw article dictionary and returns a cleaned article dictionary.
    """

    if not isinstance(article, dict):
        raise TypeError("article must be a dictionary")

    cleaned_article = deepcopy(article)

    title = clean_text(cleaned_article.get("title", ""))
    summary = clean_text(cleaned_article.get("summary", ""))
    content = clean_text(cleaned_article.get("content", ""))
    source = clean_whitespace(cleaned_article.get("source", "Unknown"))

    source_quality = score_source_quality(source)
    text_quality = score_text_quality(title, summary, content)

    cleaned_article["title"] = title
    cleaned_article["summary"] = summary
    cleaned_article["content"] = content
    cleaned_article["source"] = source
    cleaned_article["source_quality_score"] = source_quality
    cleaned_article["text_quality_score"] = text_quality
    cleaned_article["article_quality_score"] = round(
        (source_quality * 0.4) + (text_quality * 0.6),
        2,
    )
    cleaned_article["is_publishable"] = (
        cleaned_article["article_quality_score"] >= 60
        and len(title) >= 20
        and len(summary) >= 40
    )

    return cleaned_article


def clean_articles(articles):
    if not articles:
        return []

    return [clean_article(article) for article in articles]


if __name__ == "__main__":
    sample_article = {
        "title": "Heavy Rain Continues Across Andhra Pradesh as Officials Issue Alert",
        "summary": "Officials advise people to stay alert as heavy rainfall continues in several districts. Read more...",
        "content": "Heavy rainfall continued across Andhra Pradesh. Heavy rainfall continued across Andhra Pradesh. Advertisement. Officials issued alerts for low-lying areas.",
        "source": "Sample News Source",
        "url": "https://example.com/news",
    }

    cleaned = clean_article(sample_article)

    print("=" * 60)
    print("BAHUVU NEWS ARTICLE CLEANER TEST")
    print("=" * 60)
    print("Title:", cleaned["title"])
    print("Summary:", cleaned["summary"])
    print("Content:", cleaned["content"])
    print("Source:", cleaned["source"])
    print("Source Quality:", cleaned["source_quality_score"])
    print("Text Quality:", cleaned["text_quality_score"])
    print("Article Quality:", cleaned["article_quality_score"])
    print("Publishable:", cleaned["is_publishable"])
    print("=" * 60)