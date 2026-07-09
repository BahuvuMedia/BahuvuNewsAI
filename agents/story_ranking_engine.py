# agents/story_ranking_engine.py

"""
BahuvuNewsAI - Story Ranking Engine
Version: v2.3

Purpose:
- Score incoming news articles.
- Decide which stories are most important.
- Keep ranking deterministic, testable, and AI-independent.
- Prepare the newsroom pipeline for editorial prioritization.
"""

from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List, Optional

from agents.news_source_manager import SourceArticle
from agents.rss_feed_engine import RSSFeedEngine, build_test_rss_manager


CATEGORY_WEIGHTS = {
    "breaking": 35,
    "national": 30,
    "governance": 28,
    "weather": 27,
    "world": 24,
    "business": 22,
    "technology": 20,
    "health": 20,
    "sports": 15,
    "entertainment": 12,
    "general": 10,
}

REGION_WEIGHTS = {
    "andhra pradesh": 30,
    "telangana": 28,
    "india": 25,
    "world": 15,
}

BREAKING_KEYWORDS = [
    "breaking",
    "alert",
    "urgent",
    "dead",
    "killed",
    "attack",
    "blast",
    "earthquake",
    "flood",
    "rain",
    "cyclone",
    "storm",
    "fire",
    "crash",
    "war",
    "strike",
    "rescue",
    "evacuation",
    "emergency",
]

PUBLIC_IMPACT_KEYWORDS = [
    "government",
    "minister",
    "police",
    "court",
    "supreme court",
    "high court",
    "election",
    "budget",
    "prices",
    "school",
    "students",
    "farmers",
    "hospital",
    "public",
    "officials",
    "district",
]


def parse_article_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    try:
        return parsedate_to_datetime(value).replace(tzinfo=None)
    except Exception:
        pass

    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except Exception:
        return None


def score_recency(published_at: Optional[str]) -> int:
    article_time = parse_article_datetime(published_at)

    if not article_time:
        return 10

    now = datetime.now()
    age_hours = max((now - article_time).total_seconds() / 3600, 0)

    if age_hours <= 3:
        return 30
    if age_hours <= 6:
        return 25
    if age_hours <= 12:
        return 20
    if age_hours <= 24:
        return 15
    if age_hours <= 48:
        return 10

    return 5


def keyword_score(text: str, keywords: List[str], points: int) -> int:
    text_lower = text.lower()
    score = 0

    for keyword in keywords:
        if keyword in text_lower:
            score += points

    return score


def score_article(article: SourceArticle) -> int:
    title = article.title or ""
    summary = article.summary or ""
    full_text = f"{title} {summary}"

    category = (article.category or "general").lower()
    region = (article.region or "world").lower()

    score = 0

    score += CATEGORY_WEIGHTS.get(category, CATEGORY_WEIGHTS["general"])
    score += REGION_WEIGHTS.get(region, 10)
    score += score_recency(article.published_at)

    score += keyword_score(full_text, BREAKING_KEYWORDS, 4)
    score += keyword_score(full_text, PUBLIC_IMPACT_KEYWORDS, 2)

    if len(title.split()) >= 5:
        score += 5

    if article.url:
        score += 3

    if article.image_url:
        score += 3

    return min(score, 100)


def rank_articles(articles: List[SourceArticle]) -> List[SourceArticle]:
    for article in articles:
        article.importance_score = score_article(article)

    return sorted(
        articles,
        key=lambda item: item.importance_score,
        reverse=True,
    )


def get_top_stories(
    articles: List[SourceArticle],
    limit: int = 5,
) -> List[SourceArticle]:
    ranked_articles = rank_articles(articles)
    return ranked_articles[:limit]


if __name__ == "__main__":
    manager = build_test_rss_manager()
    rss_engine = RSSFeedEngine(manager)

    articles = rss_engine.fetch_latest_articles(limit_per_source=5)
    ranked_articles = rank_articles(articles)

    print("=" * 60)
    print("BahuvuNewsAI Story Ranking Engine v2.3")
    print("=" * 60)
    print(f"Articles received: {len(articles)}")
    print(f"Articles ranked  : {len(ranked_articles)}")
    print("-" * 60)

    for index, article in enumerate(ranked_articles, start=1):
        print(f"{index}. Score {article.importance_score:03d} | {article.title}")
        print(f"   Source   : {article.source_name}")
        print(f"   Category : {article.category}")
        print(f"   Region   : {article.region}")
        print(f"   URL      : {article.url}")
        print()