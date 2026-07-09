# agents/news_ranker.py

"""
BahuvuNewsAI - News Ranker
Version: v1.7

Ranks cleaned and filtered news articles by editorial importance.

This module assigns ranking scores.
It does not fetch, clean, filter, translate, or generate content.
"""

from agents.config import PREFERRED_KEYWORDS


SOURCE_WEIGHTS = {
    "Google News RSS": 5,
    "Test Source": 1,
}

CATEGORY_KEYWORDS = {
    "weather": ["rain", "flood", "storm", "cyclone", "heatwave", "alert"],
    "government": ["government", "minister", "assembly", "policy", "scheme"],
    "crime": ["police", "arrest", "case", "court", "investigation"],
    "education": ["school", "college", "exam", "students", "education"],
    "health": ["hospital", "health", "disease", "medical", "doctor"],
}


def normalize_text(text):
    """Normalize text for scoring."""
    if not text:
        return ""
    return str(text).strip().lower()


def keyword_score(article):
    """Score article using preferred editorial keywords."""
    title = normalize_text(article.get("title", ""))
    description = normalize_text(article.get("description", ""))
    combined_text = f"{title} {description}"

    score = 0

    for keyword in PREFERRED_KEYWORDS:
        if keyword.lower() in combined_text:
            score += 10

    return score


def source_score(article):
    """Score article based on source credibility/priority."""
    source = article.get("source", "")
    return SOURCE_WEIGHTS.get(source, 0)


def category_score(article):
    """Add score based on detected news category."""
    title = normalize_text(article.get("title", ""))
    description = normalize_text(article.get("description", ""))
    combined_text = f"{title} {description}"

    score = 0

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in combined_text:
                score += 5

    return score


def length_quality_score(article):
    """Give small bonus for article having usable title and description."""
    title = str(article.get("title", "")).strip()
    description = str(article.get("description", "")).strip()

    score = 0

    if len(title) >= 40:
        score += 5

    if len(description) >= 80:
        score += 5

    return score


def calculate_rank_score(article):
    """Calculate final editorial ranking score."""
    return (
        keyword_score(article)
        + source_score(article)
        + category_score(article)
        + length_quality_score(article)
    )


def rank_article(article):
    """Return a ranked copy of a single article."""
    ranked = dict(article)
    ranked["rank_score"] = calculate_rank_score(ranked)
    return ranked


def rank_articles(articles):
    """Rank a list of article dictionaries."""
    if not articles:
        return []

    ranked_articles = []

    for article in articles:
        ranked_articles.append(rank_article(article))

    ranked_articles.sort(
        key=lambda item: item.get("rank_score", 0),
        reverse=True,
    )

    return ranked_articles


def get_top_article(articles):
    """Return highest-ranked article, or None."""
    ranked_articles = rank_articles(articles)

    if not ranked_articles:
        return None

    return ranked_articles[0]


if __name__ == "__main__":
    sample_articles = [
        {
            "title": "Heavy Rain Alert Issued Across Andhra Pradesh Districts",
            "description": "Officials advise people to stay alert as rainfall continues in several districts.",
            "source": "Google News RSS",
        },
        {
            "title": "College Exam Schedule Announced for Telangana Students",
            "description": "Education department officials released the latest schedule for students.",
            "source": "Google News RSS",
        },
    ]

    ranked = rank_articles(sample_articles)

    print("Ranked articles:", len(ranked))

    for article in ranked:
        print(article["rank_score"], "-", article["title"])